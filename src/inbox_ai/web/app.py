"""FastAPI web application exposing Inbox AI data."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from urllib.parse import parse_qsl, urlencode

from datetime import UTC, datetime

from fastapi import Depends, FastAPI, Form, Request, status as http_status
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from dotenv import dotenv_values
from starlette.datastructures import UploadFile
from starlette.responses import Response
from starlette.templating import Jinja2Templates

from inbox_ai.core import AppSettings, load_app_settings
from inbox_ai.core.datetime_utils import display_datetime, serialize_datetime
from inbox_ai.core.models import (
    DraftRecord,
    EmailCategory,
    EmailEnvelope,
    EmailInsight,
    FollowUpTask,
)
from inbox_ai.ingestion import EmailParser, MailFetcher
from inbox_ai.intelligence import (
    DraftingError,
    DraftingService,
    FollowUpPlannerService,
    KeywordCategoryService,
    LLMCategoryService,
    LLMError,
    OllamaClient,
    SummarizationService,
)
from inbox_ai.storage import SqliteEmailRepository
from inbox_ai.storage.connection_pool import ConnectionPool
from inbox_ai.transport import ImapClient, ImapError
from .cache import response_cache
from .security import CSRF_FIELD_NAME, CsrfProtector

DEFAULT_LIMIT = 20
MAX_LIMIT = 100
_FOLLOW_STATUS_OPTIONS: tuple[str, ...] = ("open", "done", "all")
_PRIORITY_LABELS: Mapping[int, str] = {
    0: "Low",
    1: "Low",
    2: "Low",
    3: "Moderate",
    4: "Moderate",
    5: "Normal",
    6: "Normal",
    7: "High",
    8: "High",
    9: "Urgent",
    10: "Urgent",
}

_PRIORITY_FILTER_MAP: dict[str, tuple[int | None, int | None]] = {
    "all": (None, None),
    "urgent": (9, 10),
    "high": (7, 8),
    "normal": (5, 6),
    "moderate": (3, 4),
    "low": (0, 2),
}

_PRIORITY_FILTER_OPTIONS: tuple[tuple[str, str], ...] = (
    ("all", "All priorities"),
    ("urgent", "Urgent (9-10)"),
    ("high", "High (7-8)"),
    ("normal", "Normal (5-6)"),
    ("moderate", "Moderate (3-4)"),
    ("low", "Low (0-2)"),
)

_STATUS_QUERY_KEYS: tuple[str, ...] = (
    "sync_status",
    "sync_message",
    "delete_status",
    "delete_message",
    "categorize_status",
    "categorize_message",
    "config_status",
    "draft_status",
    "draft_message",
    "clear_status",
    "clear_message",
)


MANUAL_DRAFT_PROVIDER = "manual-edit"


LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class DashboardFilters:
    """Container for dashboard query parameters."""

    insights_limit: int
    follow_limit: int
    follow_status_filter: str | None
    follow_status_value: str
    priority_filter: str
    category_key: str | None
    follow_only: bool


@dataclass(frozen=True)
class ConfigField:
    """Metadata describing a configurable environment variable."""

    key: str
    label: str
    input_type: str = "text"
    options: tuple[str, ...] | None = None
    description: str | None = None
    textarea_rows: int | None = None


@dataclass(frozen=True)
class ConfigSection:
    """Logical grouping of configuration fields for display."""

    title: str
    fields: tuple[ConfigField, ...]


@dataclass(frozen=True)
class SyncOutcome:
    """Result of a manual synchronization request."""

    success: bool
    message: str


@dataclass(frozen=True)
class DeleteOutcome:
    """Result of a mailbox deletion request."""

    success: bool
    message: str


@dataclass(frozen=True)
class DraftRegenerationOutcome:
    """Result of regenerating a draft using the drafting service."""

    success: bool
    message: str


@dataclass(frozen=True)
class CategoryRefreshOutcome:
    """Result of a recategorisation request."""

    success: bool
    message: str


@dataclass(frozen=True)
class ClearDatabaseOutcome:
    """Result of a database clear request."""

    success: bool
    message: str


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = Path(__file__).resolve().parent / "static"
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_ENV_FILE = _PROJECT_ROOT / ".env"
_ENV_FILE_OVERRIDE_VAR = "INBOX_AI_DASHBOARD_ENV_FILE"

_BOOLEAN_OPTIONS: tuple[str, ...] = ("true", "false")

CONFIG_SECTIONS: tuple[ConfigSection, ...] = (
    ConfigSection(
        title="IMAP Connectivity",
        fields=(
            ConfigField("INBOX_AI_IMAP__HOST", "Host"),
            ConfigField("INBOX_AI_IMAP__PORT", "Port", input_type="number"),
            ConfigField("INBOX_AI_IMAP__USERNAME", "Username"),
            ConfigField("INBOX_AI_IMAP__APP_PASSWORD", "App Password"),
            ConfigField("INBOX_AI_IMAP__MAILBOXES", "Mailboxes"),
            ConfigField("INBOX_AI_IMAP__TRASH_FOLDER", "Trash Folder"),
            ConfigField(
                "INBOX_AI_IMAP__USE_SSL",
                "Use SSL",
                input_type="select",
                options=_BOOLEAN_OPTIONS,
            ),
        ),
    ),
    ConfigSection(
        title="LLM Provider",
        fields=(
            ConfigField("INBOX_AI_LLM__BASE_URL", "Base URL"),
            ConfigField("INBOX_AI_LLM__MODEL", "Model"),
            ConfigField(
                "INBOX_AI_LLM__TIMEOUT_SECONDS",
                "Timeout (seconds)",
                input_type="number",
            ),
            ConfigField("INBOX_AI_LLM__TEMPERATURE", "Temperature"),
            ConfigField(
                "INBOX_AI_LLM__MAX_OUTPUT_TOKENS",
                "Max Output Tokens",
                input_type="number",
            ),
            ConfigField(
                "INBOX_AI_LLM__FALLBACK_ENABLED",
                "Fallback Enabled",
                input_type="select",
                options=_BOOLEAN_OPTIONS,
            ),
        ),
    ),
    ConfigSection(
        title="Storage",
        fields=(ConfigField("INBOX_AI_STORAGE__DB_PATH", "Database Path"),),
    ),
    ConfigSection(
        title="Sync",
        fields=(
            ConfigField("INBOX_AI_SYNC__BATCH_SIZE", "Batch Size", input_type="number"),
            ConfigField(
                "INBOX_AI_SYNC__MAX_MESSAGES",
                "Max Messages",
                input_type="number",
                description="Leave blank to process all available messages",
            ),
        ),
    ),
    ConfigSection(
        title="Logging",
        fields=(
            ConfigField("INBOX_AI_LOGGING__LEVEL", "Level"),
            ConfigField(
                "INBOX_AI_LOGGING__STRUCTURED",
                "Structured",
                input_type="select",
                options=_BOOLEAN_OPTIONS,
            ),
        ),
    ),
    ConfigSection(
        title="Follow-Up Scheduler",
        fields=(
            ConfigField(
                "INBOX_AI_FOLLOW_UP__DEFAULT_DUE_DAYS",
                "Default Due Days",
                input_type="number",
            ),
            ConfigField(
                "INBOX_AI_FOLLOW_UP__PRIORITY_DUE_DAYS",
                "Priority Due Days",
                input_type="number",
            ),
            ConfigField(
                "INBOX_AI_FOLLOW_UP__PRIORITY_THRESHOLD",
                "Priority Threshold",
                input_type="number",
            ),
        ),
    ),
    ConfigSection(
        title="User Preferences",
        fields=(
            ConfigField(
                "INBOX_AI_USER__PREFERENCES",
                "Guidance",
                input_type="textarea",
                textarea_rows=6,
                description=(
                    "Optional context describing what matters to you. Example: "
                    "I don't care about Facebook notifications; flag security alerts as urgent."
                ),
            ),
        ),
    ),
)

CONFIG_FIELD_KEYS: tuple[str, ...] = tuple(
    field.key for section in CONFIG_SECTIONS for field in section.fields
)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    env_file = _resolve_env_file()
    app_settings = settings or load_app_settings(env_file=env_file)
    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    app = FastAPI(title="Inbox AI Dashboard")

    # Add GZip compression middleware (compress responses > 1KB)
    app.add_middleware(GZipMiddleware, minimum_size=1000)

    csrf = CsrfProtector()
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Initialize connection pool
    connection_pool = ConnectionPool(app_settings.storage, pool_size=5)

    # Simple in-memory rate limiting for manual sync requests.
    RATE_LIMIT_MAX_CALLS = 2
    RATE_LIMIT_WINDOW_SECONDS = 60
    sync_rate_lock = asyncio.Lock()
    sync_rate_history: deque[float] = deque()

    def get_repository() -> Iterator[SqliteEmailRepository]:
        with connection_pool.acquire(timeout=10.0) as repository:
            yield repository

    @app.on_event("shutdown")
    async def shutdown_event():
        """Close connection pool on app shutdown."""
        connection_pool.close()
        LOGGER.info("Connection pool closed")

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> HTMLResponse:
        filters = _parse_dashboard_filters(request.query_params)

        # Generate cache key from filters and query params
        cache_key = response_cache.make_key(
            "dashboard",
            filters.insights_limit,
            filters.priority_filter,
            filters.category_key,
            filters.follow_only,
            request.query_params.get("config_status"),
            request.query_params.get("sync_status"),
            request.query_params.get("delete_status"),
        )

        # Try to get from cache
        cached_response = response_cache.get(cache_key)
        if cached_response is not None:
            LOGGER.debug("Serving dashboard from cache")
            cached_headers = cached_response.get("headers", {})
            cached_body = cached_response.get("body", "")
            cached_media_type = cached_response.get("media_type")
            cached_status = cached_response.get("status_code", http_status.HTTP_200_OK)

            response = HTMLResponse(content=cached_body, status_code=cached_status)
            if cached_media_type:
                response.media_type = cached_media_type

            for header_key, header_value in cached_headers.items():
                if header_key.lower() in {"content-length", "content-type"}:
                    continue
                response.headers[header_key] = header_value

            return response

        # Cache miss - build response
        min_priority, max_priority = _PRIORITY_FILTER_MAP[filters.priority_filter]
        insights = repository.list_recent_insights(
            limit=filters.insights_limit,
            min_priority=min_priority,
            max_priority=max_priority,
            category_key=filters.category_key,
            require_follow_up=filters.follow_only,
        )
        total_insights = repository.count_insights(
            min_priority=min_priority,
            max_priority=max_priority,
            category_key=filters.category_key,
            require_follow_up=filters.follow_only,
        )
        draft_records = repository.list_recent_drafts(limit=filters.insights_limit)
        insight_uids = [email.uid for email, _ in insights]
        draft_lookup = repository.fetch_latest_drafts(insight_uids)
        category_lookup = repository.get_categories_for_uids(insight_uids)
        follow_up_lookup = repository.fetch_follow_ups_for_uids(insight_uids)
        category_options = repository.list_categories()
        total_email_count = repository.count_emails()
        csrf_token = csrf.generate_token()
        context = {
            "request": request,
            "insights": [
                _serialize_insight(
                    email,
                    insight,
                    draft_lookup.get(email.uid),
                    category_lookup.get(email.uid, ()),
                    follow_up_lookup.get(email.uid, ()),
                )
                for email, insight in insights
            ],
            "insights_total": total_insights,
            "drafts": [_serialize_draft(draft) for draft in draft_records],
            "filters": filters,
            "priority_filter_options": _PRIORITY_FILTER_OPTIONS,
            "category_options": category_options,
            "redirect_to": _build_redirect_target(request),
            "config_status": request.query_params.get("config_status"),
            "sync_status": request.query_params.get("sync_status"),
            "sync_message": request.query_params.get("sync_message"),
            "delete_status": request.query_params.get("delete_status"),
            "delete_message": request.query_params.get("delete_message"),
            "categorize_status": request.query_params.get("categorize_status"),
            "categorize_message": request.query_params.get("categorize_message"),
            "draft_status": request.query_params.get("draft_status"),
            "draft_message": request.query_params.get("draft_message"),
            "clear_status": request.query_params.get("clear_status"),
            "clear_message": request.query_params.get("clear_message"),
            "total_email_count": total_email_count,
            "csrf_token": csrf_token,
            "csrf_field_name": csrf.field_name,
            "manual_draft_provider": MANUAL_DRAFT_PROVIDER,
            "imap_username": app_settings.imap.username,
        }
        response = templates.TemplateResponse("index.html", context)
        csrf.set_cookie(response, csrf_token, secure=request.url.scheme == "https")

        # Cache for 5 minutes (don't cache responses with status messages)
        if not any(
            [
                request.query_params.get("config_status"),
                request.query_params.get("sync_status"),
                request.query_params.get("delete_status"),
                request.query_params.get("categorize_status"),
                request.query_params.get("draft_status"),
                request.query_params.get("clear_status"),
            ]
        ):
            # Access response body directly for caching
            body_bytes = response.body or b""
            if body_bytes:
                charset = response.charset or "utf-8"
                if isinstance(body_bytes, memoryview):
                    body_bytes = body_bytes.tobytes()
                body_text = body_bytes.decode(charset)
                response_cache.set(
                    cache_key,
                    {
                        "body": body_text,
                        "media_type": response.media_type,
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                    },
                    ttl_seconds=300,
                )
                LOGGER.debug("Cached dashboard response")

        return response

    @app.get("/settings", response_class=HTMLResponse)
    async def settings_page(
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> HTMLResponse:
        env_file = _resolve_env_file()
        config_values = _load_env_values(env_file)
        user_preferences = repository.get_all_user_preferences()
        redirect_target = _build_redirect_target(request)
        csrf_token = csrf.generate_token()
        context = {
            "request": request,
            "config_sections": CONFIG_SECTIONS,
            "config_values": config_values,
            "user_preferences": user_preferences,
            "config_status": request.query_params.get("config_status"),
            "config_env_path": str(env_file),
            "redirect_to": redirect_target,
            "csrf_token": csrf_token,
            "csrf_field_name": csrf.field_name,
            "imap_username": app_settings.imap.username,
        }
        response = templates.TemplateResponse("settings.html", context)
        csrf.set_cookie(response, csrf_token, secure=request.url.scheme == "https")
        return response

    @app.get("/api/preferences")
    async def get_preferences(
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> dict[str, str]:
        """Retrieve all user preferences."""
        return repository.get_all_user_preferences()

    @app.post("/api/preferences")
    async def set_preference(
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> dict[str, Any]:
        """Store or update a user preference."""
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)

        key = _coerce_form_value(form.get("key"))
        value = _coerce_form_value(form.get("value"))

        if not key:
            return {"success": False, "error": "Preference key is required"}

        repository.set_user_preference(key, value)
        response_cache.invalidate("dashboard")
        return {"success": True, "key": key}

    @app.delete("/api/preferences/{key}")
    async def delete_preference(
        key: str,
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> dict[str, Any]:
        """Delete a user preference."""
        csrf_token = request.headers.get("X-CSRF-Token")
        csrf.validate(request, csrf_token)

        deleted = repository.delete_user_preference(key)
        if deleted:
            response_cache.invalidate("dashboard")
        return {"success": deleted}

    @app.get("/api/dashboard")
    async def dashboard(
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> dict[str, Any]:
        filters = _parse_dashboard_filters(request.query_params)
        min_priority, max_priority = _PRIORITY_FILTER_MAP[filters.priority_filter]
        insights = repository.list_recent_insights(
            limit=filters.insights_limit,
            min_priority=min_priority,
            max_priority=max_priority,
            category_key=filters.category_key,
            require_follow_up=filters.follow_only,
        )
        total_insights = repository.count_insights(
            min_priority=min_priority,
            max_priority=max_priority,
            category_key=filters.category_key,
            require_follow_up=filters.follow_only,
        )
        draft_records = repository.list_recent_drafts(limit=filters.insights_limit)
        insight_uids = [email.uid for email, _ in insights]
        draft_lookup = repository.fetch_latest_drafts(insight_uids)
        category_lookup = repository.get_categories_for_uids(insight_uids)
        follow_up_lookup = repository.fetch_follow_ups_for_uids(insight_uids)
        category_options = repository.list_categories()
        flattened_follow_ups = [
            _serialize_follow_up(task)
            for tasks in follow_up_lookup.values()
            for task in tasks
        ]
        return {
            "insights": [
                _serialize_insight(
                    email,
                    insight,
                    draft_lookup.get(email.uid),
                    category_lookup.get(email.uid, ()),
                    follow_up_lookup.get(email.uid, ()),
                )
                for email, insight in insights
            ],
            "insightsTotal": total_insights,
            "drafts": [_serialize_draft(draft) for draft in draft_records],
            "followUps": flattened_follow_ups,
            "filters": {
                "insightsLimit": filters.insights_limit,
                "followLimit": filters.follow_limit,
                "followStatus": filters.follow_status_value,
                "priority": filters.priority_filter,
                "category": filters.category_key,
                "followOnly": filters.follow_only,
            },
            "availableCategories": [
                {"key": option.key, "label": option.label}
                for option in category_options
            ],
        }

    @app.get("/api/email/{uid}/detail")
    async def email_detail(
        uid: int,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> dict[str, Any]:
        """Lazy load detailed email content (body, insight, categories, follow-ups, draft)."""
        email = repository.fetch_email(uid)
        if not email:
            return {"error": "Email not found"}

        insight = repository.fetch_insight(uid)
        if not insight:
            return {"error": "Insight not found"}

        # Fetch related data
        categories = repository.get_categories_for_uids([uid]).get(uid, ())
        follow_ups = repository.fetch_follow_ups_for_uids([uid]).get(uid, ())
        draft_lookup = repository.fetch_latest_drafts([uid])
        draft = draft_lookup.get(uid)

        return {
            "uid": uid,
            "bodyText": email.body.text,
            "bodyHtml": email.body.html,
            "insight": _serialize_insight(
                email, insight, draft, categories, follow_ups
            ),
        }

    @app.post("/config")
    async def update_configuration(
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> RedirectResponse:
        nonlocal app_settings
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)
        env_file = _resolve_env_file()
        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        # Separate user preferences from config fields
        preference_keys = {"INBOX_AI_USER__PREFERENCES"}
        updates: dict[str, str] = {}
        preferences: dict[str, str] = {}

        for key in CONFIG_FIELD_KEYS:
            value = _coerce_form_value(form.get(key))
            if key in preference_keys:
                preferences[key] = value
            else:
                updates[key] = value

        # Save user preferences to database
        if preferences:
            for key, value in preferences.items():
                if key == "INBOX_AI_USER__PREFERENCES":
                    repository.set_user_preference("guidance", value)

        # Save config updates to .env file
        try:
            _update_env_file(env_file, updates)
        except OSError:
            failure_target = _append_query_param(
                redirect_target, "config_status", "error"
            )
            return RedirectResponse(
                url=failure_target, status_code=http_status.HTTP_303_SEE_OTHER
            )

        for key, value in updates.items():
            if value == "":
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        load_app_settings.cache_clear()
        app_settings = load_app_settings(env_file=_resolve_env_file())

        success_target = _append_query_param(redirect_target, "config_status", "saved")
        return RedirectResponse(
            url=success_target, status_code=http_status.HTTP_303_SEE_OTHER
        )

    @app.post("/sync")
    async def trigger_sync(request: Request) -> Response:
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)
        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        async with sync_rate_lock:
            now = time.monotonic()
            while (
                sync_rate_history
                and now - sync_rate_history[0] > RATE_LIMIT_WINDOW_SECONDS
            ):
                sync_rate_history.popleft()
            if len(sync_rate_history) >= RATE_LIMIT_MAX_CALLS:
                target = _append_query_param(redirect_target, "sync_status", "error")
                target = _append_query_param(
                    target,
                    "sync_message",
                    "Too many sync requests. Please wait before trying again.",
                )
                return RedirectResponse(
                    url=target, status_code=http_status.HTTP_303_SEE_OTHER
                )
            sync_rate_history.append(now)

        # Check credentials before starting sync
        if not app_settings.imap.username or not app_settings.imap.app_password:
            target = _append_query_param(redirect_target, "sync_status", "error")
            target = _append_query_param(
                target,
                "sync_message",
                "Configure IMAP username and app password before syncing.",
            )
            return RedirectResponse(
                url=target, status_code=http_status.HTTP_303_SEE_OTHER
            )

        queue: asyncio.Queue[str] = asyncio.Queue()

        async def run_sync():
            outcome = await asyncio.to_thread(_run_sync_cycle, app_settings, queue)

            # Invalidate cache after sync completes
            invalidated = response_cache.invalidate("dashboard")
            LOGGER.info(
                "Invalidated %d dashboard cache entries after sync", invalidated
            )

            status_value = "ok" if outcome.success else "error"
            target = _append_query_param(redirect_target, "sync_status", status_value)
            target = _append_query_param(target, "sync_message", outcome.message)
            queue.put_nowait(f"redirect:{target}")

        asyncio.create_task(run_sync())

        async def generate():
            while True:
                message = await queue.get()
                if message.startswith("redirect:"):
                    yield f"data: {message}\n\n"
                    break
                yield f"data: {message}\n\n"

        return StreamingResponse(generate(), media_type="text/event-stream")

    @app.post("/categories/regenerate")
    async def regenerate_categories(request: Request) -> RedirectResponse:
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)
        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        outcome = await asyncio.to_thread(_regenerate_categories, app_settings)
        status_value = "ok" if outcome.success else "error"
        target = _append_query_param(redirect_target, "categorize_status", status_value)
        target = _append_query_param(target, "categorize_message", outcome.message)
        return RedirectResponse(url=target, status_code=http_status.HTTP_303_SEE_OTHER)

    @app.post("/clear-database")
    async def clear_database(request: Request) -> RedirectResponse:
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)
        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        outcome = await asyncio.to_thread(_clear_database, app_settings)
        status_value = "ok" if outcome.success else "error"
        target = _append_query_param(redirect_target, "clear_status", status_value)
        target = _append_query_param(target, "clear_message", outcome.message)
        return RedirectResponse(url=target, status_code=http_status.HTTP_303_SEE_OTHER)

    @app.post("/emails/{email_uid}/delete")
    async def delete_email(
        request: Request,
        email_uid: int,
        redirect_to: str | None = Form(None),
        csrf_token: str = Form(..., alias=CSRF_FIELD_NAME),
    ) -> RedirectResponse:
        csrf.validate(request, csrf_token)
        redirect_target = _sanitize_redirect(redirect_to) or "/"
        outcome = await asyncio.to_thread(_delete_email, app_settings, email_uid)

        # Invalidate cache after delete
        if outcome.success:
            response_cache.invalidate("dashboard")
            LOGGER.info("Invalidated cache after deleting email %s", email_uid)

        status_value = "ok" if outcome.success else "error"
        target = _append_query_param(redirect_target, "delete_status", status_value)
        target = _append_query_param(target, "delete_message", outcome.message)
        return RedirectResponse(url=target, status_code=http_status.HTTP_303_SEE_OTHER)

    @app.post("/emails/bulk-delete")
    async def bulk_delete_emails(request: Request) -> RedirectResponse:
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)
        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        raw_uids = form.getlist("uids") if hasattr(form, "getlist") else []
        uids: list[int] = []
        for raw in raw_uids:
            try:
                value = int(str(raw))
            except (TypeError, ValueError):
                continue
            uids.append(value)

        outcome = await asyncio.to_thread(_delete_emails, app_settings, tuple(uids))

        # Invalidate cache after bulk delete
        if outcome.success:
            response_cache.invalidate("dashboard")
            LOGGER.info("Invalidated cache after bulk deleting %d emails", len(uids))

        status_value = "ok" if outcome.success else "error"
        target = _append_query_param(redirect_target, "delete_status", status_value)
        target = _append_query_param(target, "delete_message", outcome.message)
        return RedirectResponse(url=target, status_code=http_status.HTTP_303_SEE_OTHER)

    @app.post("/emails/{email_uid}/draft")
    async def update_draft(
        email_uid: int,
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> RedirectResponse:
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)

        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        body_raw = _coerce_form_value(form.get("body"))
        if body_raw.strip() == "":
            failure_target = _append_query_param(
                redirect_target, "draft_status", "error"
            )
            failure_target = _append_query_param(
                failure_target, "draft_message", "Draft body cannot be empty."
            )
            return RedirectResponse(
                url=failure_target, status_code=http_status.HTTP_303_SEE_OTHER
            )

        draft_id_raw = _coerce_form_value(form.get("draft_id")).strip()
        provider_raw = _coerce_form_value(form.get("provider"))
        provider = provider_raw.strip() or MANUAL_DRAFT_PROVIDER
        generated_at = datetime.now(UTC)

        draft_id: int | None = None
        if draft_id_raw:
            try:
                draft_id = int(draft_id_raw)
            except ValueError:
                draft_id = None

        updated = False
        if draft_id is not None:
            updated_record = repository.update_draft_body(
                draft_id,
                email_uid,
                body=body_raw,
                provider=provider,
                generated_at=generated_at,
                confidence=None,
                used_fallback=False,
            )
            updated = updated_record is not None

        if not updated:
            repository.persist_draft(
                DraftRecord(
                    id=None,
                    email_uid=email_uid,
                    body=body_raw,
                    provider=provider,
                    generated_at=generated_at,
                    confidence=None,
                    used_fallback=False,
                )
            )

        success_target = _append_query_param(redirect_target, "draft_status", "ok")
        success_target = _append_query_param(
            success_target, "draft_message", "Draft updated successfully."
        )
        return RedirectResponse(
            url=success_target, status_code=http_status.HTTP_303_SEE_OTHER
        )

    @app.post("/emails/{email_uid}/draft/regenerate")
    async def regenerate_draft(
        email_uid: int,
        request: Request,
    ) -> RedirectResponse:
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)

        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        draft_id_raw = _coerce_form_value(form.get("draft_id")).strip()
        draft_id: int | None = None
        if draft_id_raw:
            try:
                draft_id = int(draft_id_raw)
            except ValueError:
                draft_id = None

        outcome = await asyncio.to_thread(
            _regenerate_draft,
            app_settings,
            email_uid,
            draft_id,
        )
        status_value = "ok" if outcome.success else "error"
        target = _append_query_param(redirect_target, "draft_status", status_value)
        target = _append_query_param(target, "draft_message", outcome.message)
        return RedirectResponse(url=target, status_code=http_status.HTTP_303_SEE_OTHER)

    @app.post("/emails/{email_uid}/draft/delete")
    async def delete_draft(
        email_uid: int,
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> RedirectResponse:
        form = await request.form()
        raw_token = form.get(csrf.field_name)
        token = raw_token if isinstance(raw_token, str) else None
        csrf.validate(request, token)

        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        draft_id_raw = _coerce_form_value(form.get("draft_id")).strip()
        draft_id: int | None = None
        if draft_id_raw:
            try:
                draft_id = int(draft_id_raw)
            except ValueError:
                draft_id = None

        if draft_id is None:
            failure_target = _append_query_param(
                redirect_target, "draft_status", "error"
            )
            failure_target = _append_query_param(
                failure_target, "draft_message", "Draft could not be deleted."
            )
            return RedirectResponse(
                url=failure_target, status_code=http_status.HTTP_303_SEE_OTHER
            )

        deleted = repository.delete_draft(draft_id, email_uid)
        status_key = "ok" if deleted else "error"
        message = "Draft deleted." if deleted else "Draft could not be deleted."
        target = _append_query_param(redirect_target, "draft_status", status_key)
        target = _append_query_param(target, "draft_message", message)
        return RedirectResponse(url=target, status_code=http_status.HTTP_303_SEE_OTHER)

    @app.post("/follow-ups/{follow_up_id}/status")
    async def update_follow_up_status(
        request: Request,
        follow_up_id: int,
        status_value: str = Form(..., alias="status"),
        redirect_to: str | None = Form(None),
        csrf_token: str = Form(..., alias=CSRF_FIELD_NAME),
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> RedirectResponse:
        csrf.validate(request, csrf_token)
        target_status = _normalize_status_update(status_value)
        repository.update_follow_up_status(follow_up_id, target_status)
        redirect_target = _sanitize_redirect(redirect_to) or "/"
        return RedirectResponse(
            url=redirect_target,
            status_code=http_status.HTTP_303_SEE_OTHER,
        )

    _ensure_route_names(app)
    return app


def _ensure_route_names(app: FastAPI) -> None:
    """Assign names to routes if absent for better URL reversing."""
    for route in app.router.routes:
        if isinstance(route, APIRoute) and route.name is None:
            route.name = route.path_format.replace("/", ":") or "root"


def _serialize_insight(
    email: EmailEnvelope,
    insight: EmailInsight,
    draft: DraftRecord | None = None,
    categories: Sequence[EmailCategory] | None = None,
    follow_ups: Sequence[FollowUpTask] | None = None,
) -> dict[str, Any]:
    return {
        "uid": email.uid,
        "subject": email.subject,
        "sender": email.sender,
        "threadId": email.thread_id,
        "receivedAt": serialize_datetime(email.received_at),
        "receivedAtDisplay": display_datetime(email.received_at),
        "summary": insight.summary,
        "actionItems": list(insight.action_items),
        "categories": [
            {"key": category.key, "label": category.label}
            for category in (categories or ())
        ],
        "followUps": [_serialize_follow_up(task) for task in (follow_ups or ())],
        "priority": insight.priority,
        "priorityLabel": _priority_label(insight.priority),
        "provider": insight.provider,
        "generatedAt": serialize_datetime(insight.generated_at),
        "generatedAtDisplay": display_datetime(insight.generated_at),
        "draft": _serialize_draft(draft) if draft is not None else None,
    }


def _serialize_draft(draft: DraftRecord) -> dict[str, Any]:
    return {
        "id": draft.id,
        "emailUid": draft.email_uid,
        "body": draft.body,
        "provider": draft.provider,
        "confidence": draft.confidence,
        "generatedAt": serialize_datetime(draft.generated_at),
        "generatedAtDisplay": display_datetime(draft.generated_at),
        "usedFallback": draft.used_fallback,
    }


def _serialize_follow_up(task: FollowUpTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "emailUid": task.email_uid,
        "action": task.action,
        "dueAt": serialize_datetime(task.due_at),
        "status": task.status,
        "createdAt": serialize_datetime(task.created_at),
        "completedAt": serialize_datetime(task.completed_at),
    }


def _priority_label(score: int) -> str:
    return _PRIORITY_LABELS.get(score, "Normal")


def _parse_dashboard_filters(params: Mapping[str, str]) -> DashboardFilters:
    insights_limit = _parse_limit(params.get("insights_limit"), DEFAULT_LIMIT)
    follow_limit = _parse_limit(params.get("follow_limit"), DEFAULT_LIMIT)
    follow_status_filter, follow_status_value = _normalize_follow_status(
        params.get("follow_status")
    )
    priority_filter = _normalize_priority_filter(params.get("priority"))
    category_key = _normalize_category_filter(params.get("category"))
    follow_only = _parse_bool_flag(params.get("follow_only"))
    return DashboardFilters(
        insights_limit=insights_limit,
        follow_limit=follow_limit,
        follow_status_filter=follow_status_filter,
        follow_status_value=follow_status_value,
        priority_filter=priority_filter,
        category_key=category_key,
        follow_only=follow_only,
    )


def _normalize_priority_filter(raw: str | None) -> str:
    value = (raw or "all").lower()
    if value not in _PRIORITY_FILTER_MAP:
        return "all"
    return value


def _normalize_category_filter(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value or value.lower() == "all":
        return None
    return value


def _parse_bool_flag(raw: str | None) -> bool:
    if raw is None:
        return False
    value = raw.strip().lower()
    return value in {"1", "true", "yes", "on"}


def _parse_limit(raw: str | None, default: int) -> int:
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return min(value, MAX_LIMIT)


def _normalize_follow_status(raw: str | None) -> tuple[str | None, str]:
    value = (raw or "open").lower()
    if value not in _FOLLOW_STATUS_OPTIONS:
        value = "open"
    return (None if value == "all" else value, value)


def _normalize_status_update(value: str) -> str:
    return "done" if value.lower() == "done" else "open"


def _sanitize_redirect(target: str | None) -> str | None:
    if not target:
        return None
    if target.startswith("/"):
        return target
    return None


def _build_redirect_target(
    request: Request, *, exclude_keys: Iterable[str] | None = None
) -> str:
    base = request.url.path or "/"
    raw_pairs = parse_qsl(request.url.query, keep_blank_values=True)
    excluded = set(exclude_keys or _STATUS_QUERY_KEYS)
    filtered = [(key, value) for key, value in raw_pairs if key not in excluded]
    if not filtered:
        return base
    return f"{base}?{urlencode(filtered)}"


def _format_sync_error(exc: Exception) -> str:
    if isinstance(exc, ImapError):
        return (
            "Email server error: "
            f"{exc}. Verify IMAP host, credentials, and network access before retrying."
        )
    if isinstance(exc, LLMError):
        return (
            "AI service error: "
            f"{exc}. Check LLM settings or try again with fallback enabled."
        )
    return f"Sync failed: {exc}"


def _run_sync_cycle(
    settings: AppSettings, progress_queue: asyncio.Queue[str] | None = None
) -> SyncOutcome:
    missing_credentials = not settings.imap.username or not settings.imap.app_password
    if missing_credentials:
        return SyncOutcome(
            success=False,
            message="Configure IMAP username and app password before syncing.",
        )

    def _enqueue(message: str) -> None:
        if progress_queue:
            progress_queue.put_nowait(message)

    mailbox_total = len(settings.imap.mailboxes)
    if mailbox_total == 0:
        _enqueue("No mailboxes configured. Update settings to enable syncing.")
        return SyncOutcome(
            success=True, message="Sync skipped. No mailboxes configured."
        )

    _enqueue("Initialising services and preparing sync...")

    email_parser = EmailParser()
    llm_client = (
        OllamaClient(settings.llm)
        if settings.llm.base_url and settings.llm.model
        else None
    )
    drafting_service = DraftingService(
        llm_client, fallback_enabled=settings.llm.fallback_enabled
    )
    follow_up_planner = FollowUpPlannerService(settings.follow_up)
    insight_service = SummarizationService(
        llm_client, fallback_enabled=settings.llm.fallback_enabled
    )
    category_service = (
        LLMCategoryService(llm_client) if llm_client else KeywordCategoryService()
    )

    try:
        processed_total = 0
        for index, mailbox_name in enumerate(settings.imap.mailboxes, start=1):
            _enqueue(f"[{index}/{mailbox_total}] Connecting to {mailbox_name}…")
            attempt = 1
            while True:
                try:
                    with (
                        ImapClient(settings.imap, mailbox_name) as mailbox,
                        SqliteEmailRepository(settings.storage) as repository,
                    ):
                        checkpoint = repository.get_checkpoint(mailbox_name)
                        last_uid = checkpoint.last_uid if checkpoint else None
                        _enqueue(
                            f"[{index}/{mailbox_total}] Last synced UID for {mailbox_name}: {last_uid or 'none'}"
                        )
                        fetcher = MailFetcher(
                            mailbox=mailbox,
                            repository=repository,
                            parser=email_parser,
                            batch_size=settings.sync.batch_size,
                            max_messages=settings.sync.max_messages,
                            insight_service=insight_service,
                            drafting_service=drafting_service,
                            follow_up_planner=follow_up_planner,
                            category_service=category_service,
                            progress_callback=(
                                (
                                    lambda message, mailbox_name=mailbox_name: _enqueue(
                                        f"[{mailbox_name}] {message}"
                                    )
                                )
                                if progress_queue
                                else None
                            ),
                            user_email=settings.imap.username,
                        )
                        result = fetcher.run()
                        processed_total += result.processed
                        _enqueue(
                            f"[{index}/{mailbox_total}] {mailbox_name}: processed {result.processed} new message(s)."
                        )
                    break
                except ImapError as exc:
                    if attempt >= 3:
                        raise
                    delay = min(2**attempt, 10)
                    _enqueue(
                        f"[{index}/{mailbox_total}] {mailbox_name}: {exc}. Retrying in {delay} seconds..."
                    )
                    time.sleep(delay)
                    attempt += 1
        if progress_queue:
            _enqueue(f"Processed {processed_total} message(s) across all mailboxes.")
    except ImapError as exc:
        message = _format_sync_error(exc)
        _enqueue(f"Error: {message}")
        return SyncOutcome(success=False, message=message)
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        LOGGER.exception("Unexpected error during sync: %s", exc)
        message = _format_sync_error(exc)
        _enqueue(f"Error: {message}")
        return SyncOutcome(success=False, message=message)

    if processed_total == 0:
        _enqueue("Sync complete. No new messages processed.")
        return SyncOutcome(
            success=True,
            message="Sync complete. No new messages processed.",
        )
    _enqueue("Sync complete")
    return SyncOutcome(
        success=True,
        message=f"Sync complete. Processed {processed_total} message(s).",
    )


def _regenerate_categories(settings: AppSettings) -> CategoryRefreshOutcome:
    categorizer = KeywordCategoryService()
    try:
        with SqliteEmailRepository(settings.storage) as repository:
            total = repository.count_insights()
            if total == 0:
                return CategoryRefreshOutcome(
                    success=True,
                    message="No stored insights available to categorize.",
                )

            updated = 0
            failures = 0
            for email, insight in repository.list_recent_insights(limit=total):
                try:
                    categories = tuple(categorizer.categorize(email, insight))
                    repository.replace_categories(email.uid, categories)
                    updated += 1
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    failures += 1
                    LOGGER.warning(
                        "Failed to regenerate categories for UID %s: %s",
                        email.uid,
                        exc,
                    )

            if failures:
                return CategoryRefreshOutcome(
                    success=False,
                    message=(
                        f"Updated categories for {updated} emails with "
                        f"{failures} failures. Check logs for details."
                    ),
                )

            return CategoryRefreshOutcome(
                success=True,
                message=f"Updated categories for {updated} emails.",
            )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception("Category regeneration failed: %s", exc)
        return CategoryRefreshOutcome(
            success=False,
            message="Category regeneration failed. Check server logs for details.",
        )


def _clear_database(settings: AppSettings) -> ClearDatabaseOutcome:
    try:
        with SqliteEmailRepository(settings.storage) as repository:
            repository.clear_all_tables()
        return ClearDatabaseOutcome(
            success=True,
            message="Database cleared successfully.",
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        LOGGER.exception("Database clear failed: %s", exc)
        return ClearDatabaseOutcome(
            success=False,
            message="Database clear failed. Check server logs for details.",
        )


def _regenerate_draft(
    settings: AppSettings, email_uid: int, draft_id: int | None
) -> DraftRegenerationOutcome:
    try:
        with SqliteEmailRepository(settings.storage) as repository:
            email = repository.fetch_email(email_uid)
            if email is None:
                return DraftRegenerationOutcome(
                    success=False,
                    message="Draft could not be regenerated. Email data is missing.",
                )

            insight = repository.fetch_insight(email_uid)
            if insight is None:
                return DraftRegenerationOutcome(
                    success=False,
                    message="Draft could not be regenerated. Insight data is missing.",
                )

            llm_client = (
                OllamaClient(settings.llm)
                if settings.llm.base_url and settings.llm.model
                else None
            )
            drafting_service = DraftingService(
                llm_client,
                fallback_enabled=settings.llm.fallback_enabled,
            )

            try:
                generated = drafting_service.generate_draft(email, insight)
            except DraftingError as exc:
                LOGGER.warning(
                    "Draft regeneration failed for UID %s: %s",
                    email_uid,
                    exc,
                )
                return DraftRegenerationOutcome(
                    success=False,
                    message="Draft could not be regenerated.",
                )

            persisted = False
            if draft_id is not None:
                updated = repository.update_draft_body(
                    draft_id,
                    email_uid,
                    body=generated.body,
                    provider=generated.provider,
                    generated_at=generated.generated_at,
                    confidence=generated.confidence,
                    used_fallback=generated.used_fallback,
                )
                persisted = updated is not None

            if not persisted:
                repository.persist_draft(generated)

        return DraftRegenerationOutcome(success=True, message="Draft regenerated.")
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        LOGGER.exception(
            "Unexpected error regenerating draft for UID %s: %s", email_uid, exc
        )
        return DraftRegenerationOutcome(
            success=False,
            message="Draft could not be regenerated.",
        )


def _delete_email(settings: AppSettings, uid: int) -> DeleteOutcome:
    missing_credentials = not settings.imap.username or not settings.imap.app_password
    if missing_credentials:
        return DeleteOutcome(
            success=False,
            message="Configure IMAP username and app password before deleting.",
        )

    try:
        with SqliteEmailRepository(settings.storage) as repository:
            email = repository.fetch_email(uid)
            if email is None:
                return DeleteOutcome(
                    success=True, message=f"Message UID {uid} not found."
                )
            mailbox_name = email.mailbox

        with (
            ImapClient(settings.imap, mailbox_name) as mailbox,
            SqliteEmailRepository(settings.storage) as repository,
        ):
            mailbox.move_to_trash(uid, settings.imap.trash_folder)
            removed = repository.delete_email(uid)
    except ImapError as exc:
        return DeleteOutcome(success=False, message=f"Delete failed: {exc}")
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        LOGGER.exception("Unexpected error deleting UID %s: %s", uid, exc)
        return DeleteOutcome(success=False, message=f"Delete failed: {exc}")

    if removed:
        return DeleteOutcome(success=True, message=f"Message UID {uid} deleted.")
    return DeleteOutcome(
        success=True,
        message=f"Message UID {uid} deleted (no local record found).",
    )


def _delete_emails(settings: AppSettings, uids: Sequence[int]) -> DeleteOutcome:
    unique_uids = tuple(dict.fromkeys(uids))
    if not unique_uids:
        return DeleteOutcome(success=True, message="No emails to delete.")

    missing_credentials = not settings.imap.username or not settings.imap.app_password
    if missing_credentials:
        return DeleteOutcome(
            success=False,
            message="Configure IMAP username and app password before deleting.",
        )

    try:
        with SqliteEmailRepository(settings.storage) as repository:
            emails = []
            for uid in unique_uids:
                email = repository.fetch_email(uid)
                if email:
                    emails.append(email)
            if not emails:
                return DeleteOutcome(success=True, message="No emails found to delete.")

            # Group by mailbox
            by_mailbox = {}
            for email in emails:
                by_mailbox.setdefault(email.mailbox, []).append(email.uid)

        successes = 0
        failures: list[tuple[int, str]] = []
        for mailbox_name, mailbox_uids in by_mailbox.items():
            try:
                with ImapClient(settings.imap, mailbox_name) as mailbox:
                    for uid in mailbox_uids:
                        mailbox.move_to_trash(uid, settings.imap.trash_folder)
            except ImapError as exc:
                LOGGER.warning(
                    "Mailbox delete failed for mailbox %s: %s", mailbox_name, exc
                )
                for uid in mailbox_uids:
                    failures.append((uid, str(exc)))
                continue

            with SqliteEmailRepository(settings.storage) as repository:
                for uid in mailbox_uids:
                    try:
                        repository.delete_email(uid)
                    except (
                        Exception
                    ) as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
                        LOGGER.warning(
                            "Repository cleanup failed for UID %s: %s",
                            uid,
                            exc,
                        )
                        failures.append((uid, str(exc)))
                        continue
                    successes += 1
    except ImapError as exc:
        return DeleteOutcome(success=False, message=f"Delete failed: {exc}")
    except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
        LOGGER.exception("Unexpected error during bulk delete: %s", exc)
        return DeleteOutcome(success=False, message=f"Delete failed: {exc}")

    if successes == 0 and failures:
        return DeleteOutcome(
            success=False,
            message="Unable to delete the selected emails. Check server logs for details.",
        )

    if failures:
        failed_count = len(failures)
        failed_uids = ", ".join(str(uid) for uid, _ in failures)
        return DeleteOutcome(
            success=False,
            message=(
                f"Deleted {successes} email(s). Failed to delete {failed_count} "
                f"email(s): {failed_uids}. Check logs for details."
            ),
        )

    return DeleteOutcome(success=True, message=f"Deleted {successes} email(s).")


def _coerce_form_value(value: UploadFile | str | None) -> str:
    if isinstance(value, UploadFile):
        return value.filename or ""
    if value is None:
        return ""
    return value


def _resolve_env_file() -> Path:
    override = os.getenv(_ENV_FILE_OVERRIDE_VAR)
    if override:
        return Path(override)
    return _DEFAULT_ENV_FILE


def _load_env_values(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        # Fall back to current environment if the file is missing.
        return {key: os.environ.get(key, "") for key in CONFIG_FIELD_KEYS}

    values = dotenv_values(env_path)
    resolved: dict[str, str] = {}
    for key in CONFIG_FIELD_KEYS:
        value = values.get(key)
        if value is None:
            value = os.environ.get(key, "")
        resolved[key] = value or ""
    return resolved


def _update_env_file(env_path: Path, updates: Mapping[str, str]) -> None:
    env_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        existing_lines = []

    updated_lines: list[str] = []
    written_keys: set[str] = set()

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            updated_lines.append(line)
            continue
        key, _, _ = line.partition("=")
        normalized_key = key.strip()
        if normalized_key in updates:
            new_value = updates[normalized_key]
            if new_value == "":
                written_keys.add(normalized_key)
                continue
            updated_lines.append(f"{normalized_key}={_format_env_value(new_value)}")
            written_keys.add(normalized_key)
        else:
            updated_lines.append(line)

    for key, value in updates.items():
        if key not in written_keys and value != "":
            updated_lines.append(f"{key}={_format_env_value(value)}")

    content = "\n".join(updated_lines).rstrip("\n") + "\n"
    env_path.write_text(content, encoding="utf-8")


def _format_env_value(value: str) -> str:
    if value == "":
        return ""
    if any(ch.isspace() for ch in value) or "#" in value or "=" in value:
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _append_query_param(url: str, key: str, value: str) -> str:
    base, separator, query = url.partition("?")
    if separator:
        existing = dict(parse_qsl(query, keep_blank_values=True))
        existing[key] = value
        return f"{base}?{urlencode(existing)}"
    return f"{url}?{urlencode({key: value})}"
