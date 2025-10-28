"""FastAPI web application exposing Inbox AI data."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, Request, status as http_status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.routing import APIRoute
from dotenv import dotenv_values
from starlette.datastructures import UploadFile
from starlette.templating import Jinja2Templates

from urllib.parse import parse_qsl, urlencode

from inbox_ai.core import AppSettings, load_app_settings
from inbox_ai.core.models import DraftRecord, EmailEnvelope, EmailInsight, FollowUpTask
from inbox_ai.ingestion import EmailParser, MailFetcher
from inbox_ai.intelligence import (
    DraftingService,
    FollowUpPlannerService,
    OllamaClient,
    SummarizationService,
)
from inbox_ai.storage import SqliteEmailRepository
from inbox_ai.transport import ImapClient, ImapError

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

_STATUS_QUERY_KEYS: tuple[str, ...] = (
    "sync_status",
    "sync_message",
    "delete_status",
    "delete_message",
    "config_status",
)


@dataclass(slots=True)
class DashboardFilters:
    """Container for dashboard query parameters."""

    insights_limit: int
    drafts_limit: int
    follow_limit: int
    follow_status_filter: str | None
    follow_status_value: str


@dataclass(frozen=True)
class ConfigField:
    """Metadata describing a configurable environment variable."""

    key: str
    label: str
    input_type: str = "text"
    options: tuple[str, ...] | None = None
    description: str | None = None


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


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
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
            ConfigField("INBOX_AI_IMAP__MAILBOX", "Mailbox"),
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

    def get_repository() -> Iterator[SqliteEmailRepository]:
        repository = SqliteEmailRepository(app_settings.storage)
        try:
            yield repository
        finally:
            repository.close()

    @app.get("/", response_class=HTMLResponse)
    async def index(
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> HTMLResponse:
        filters = _parse_dashboard_filters(request.query_params)
        insights = repository.list_recent_insights(limit=filters.insights_limit)
        total_insights = repository.count_insights()
        draft_limit = max(filters.drafts_limit, filters.insights_limit)
        draft_records = repository.list_recent_drafts(limit=draft_limit)
        draft_lookup: dict[int, DraftRecord] = {}
        for draft in draft_records:
            if draft.email_uid not in draft_lookup:
                draft_lookup[draft.email_uid] = draft
        follow_ups = repository.list_follow_ups(
            status=filters.follow_status_filter, limit=filters.follow_limit
        )
        env_file = _resolve_env_file()
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "request": request,
                "insights": [
                    _serialize_insight(email, insight, draft_lookup.get(email.uid))
                    for email, insight in insights
                ],
                "insights_total": total_insights,
                "drafts": [_serialize_draft(draft) for draft in draft_records],
                "follow_ups": [_serialize_follow_up(task) for task in follow_ups],
                "filters": filters,
                "follow_status_options": _FOLLOW_STATUS_OPTIONS,
                "redirect_to": _build_redirect_target(request),
                "config_sections": CONFIG_SECTIONS,
                "config_values": _load_env_values(env_file),
                "config_status": request.query_params.get("config_status"),
                "config_env_path": str(env_file),
                "sync_status": request.query_params.get("sync_status"),
                "sync_message": request.query_params.get("sync_message"),
                "delete_status": request.query_params.get("delete_status"),
                "delete_message": request.query_params.get("delete_message"),
            },
        )

    @app.get("/api/dashboard")
    async def dashboard(
        request: Request,
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> dict[str, Any]:
        filters = _parse_dashboard_filters(request.query_params)
        insights = repository.list_recent_insights(limit=filters.insights_limit)
        total_insights = repository.count_insights()
        draft_limit = max(filters.drafts_limit, filters.insights_limit)
        draft_records = repository.list_recent_drafts(limit=draft_limit)
        draft_lookup: dict[int, DraftRecord] = {}
        for draft in draft_records:
            if draft.email_uid not in draft_lookup:
                draft_lookup[draft.email_uid] = draft
        follow_ups = repository.list_follow_ups(
            status=filters.follow_status_filter, limit=filters.follow_limit
        )
        return {
            "insights": [
                _serialize_insight(email, insight, draft_lookup.get(email.uid))
                for email, insight in insights
            ],
            "insightsTotal": total_insights,
            "drafts": [_serialize_draft(draft) for draft in draft_records],
            "followUps": [_serialize_follow_up(task) for task in follow_ups],
            "filters": {
                "insightsLimit": filters.insights_limit,
                "draftsLimit": filters.drafts_limit,
                "followLimit": filters.follow_limit,
                "followStatus": filters.follow_status_value,
            },
        }

    @app.post("/config")
    async def update_configuration(request: Request) -> RedirectResponse:
        nonlocal app_settings
        form = await request.form()
        env_file = _resolve_env_file()
        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"
        updates: dict[str, str] = {
            key: _coerce_form_value(form.get(key)) for key in CONFIG_FIELD_KEYS
        }
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
    async def trigger_sync(request: Request) -> RedirectResponse:
        form = await request.form()
        redirect_raw = _coerce_form_value(form.get("redirect_to"))
        redirect_target = _sanitize_redirect(redirect_raw or None) or "/"

        outcome = await asyncio.to_thread(_run_sync_cycle, app_settings)
        status_value = "ok" if outcome.success else "error"
        target = _append_query_param(redirect_target, "sync_status", status_value)
        target = _append_query_param(target, "sync_message", outcome.message)
        return RedirectResponse(url=target, status_code=http_status.HTTP_303_SEE_OTHER)

    @app.post("/emails/{email_uid}/delete")
    async def delete_email(
        email_uid: int,
        redirect_to: str | None = Form(None),
    ) -> RedirectResponse:
        redirect_target = _sanitize_redirect(redirect_to) or "/"
        outcome = await asyncio.to_thread(_delete_email, app_settings, email_uid)
        status_value = "ok" if outcome.success else "error"
        target = _append_query_param(redirect_target, "delete_status", status_value)
        target = _append_query_param(target, "delete_message", outcome.message)
        return RedirectResponse(url=target, status_code=http_status.HTTP_303_SEE_OTHER)

    @app.post("/follow-ups/{follow_up_id}/status")
    async def update_follow_up_status(
        follow_up_id: int,
        request: Request,
        status_value: str = Form(..., alias="status"),
        redirect_to: str | None = Form(None),
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> RedirectResponse:
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
) -> dict[str, Any]:
    return {
        "uid": email.uid,
        "subject": email.subject,
        "sender": email.sender,
        "summary": insight.summary,
        "actionItems": list(insight.action_items),
        "priority": insight.priority,
        "priorityLabel": _priority_label(insight.priority),
        "provider": insight.provider,
        "generatedAt": _isoformat(insight.generated_at),
        "generatedAtDisplay": _friendly_datetime(insight.generated_at),
        "draft": _serialize_draft(draft) if draft is not None else None,
    }


def _serialize_draft(draft: DraftRecord) -> dict[str, Any]:
    return {
        "id": draft.id,
        "emailUid": draft.email_uid,
        "body": draft.body,
        "provider": draft.provider,
        "confidence": draft.confidence,
        "generatedAt": _isoformat(draft.generated_at),
        "generatedAtDisplay": _friendly_datetime(draft.generated_at),
        "usedFallback": draft.used_fallback,
    }


def _serialize_follow_up(task: FollowUpTask) -> dict[str, Any]:
    return {
        "id": task.id,
        "emailUid": task.email_uid,
        "action": task.action,
        "dueAt": _isoformat(task.due_at),
        "status": task.status,
        "createdAt": _isoformat(task.created_at),
        "completedAt": _isoformat(task.completed_at),
    }


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone().isoformat()


def _friendly_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    display = value.astimezone() if value.tzinfo is not None else value
    return display.strftime("%b %d, %Y %I:%M %p")


def _priority_label(score: int) -> str:
    return _PRIORITY_LABELS.get(score, "Normal")


def _parse_dashboard_filters(params: Mapping[str, str]) -> DashboardFilters:
    insights_limit = _parse_limit(params.get("insights_limit"), DEFAULT_LIMIT)
    drafts_limit = _parse_limit(params.get("drafts_limit"), DEFAULT_LIMIT)
    follow_limit = _parse_limit(params.get("follow_limit"), DEFAULT_LIMIT)
    follow_status_filter, follow_status_value = _normalize_follow_status(
        params.get("follow_status")
    )
    return DashboardFilters(
        insights_limit=insights_limit,
        drafts_limit=drafts_limit,
        follow_limit=follow_limit,
        follow_status_filter=follow_status_filter,
        follow_status_value=follow_status_value,
    )


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


def _run_sync_cycle(settings: AppSettings) -> SyncOutcome:
    missing_credentials = not settings.imap.username or not settings.imap.app_password
    if missing_credentials:
        return SyncOutcome(
            success=False,
            message="Configure IMAP username and app password before syncing.",
        )

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

    try:
        with (
            ImapClient(settings.imap) as mailbox,
            SqliteEmailRepository(settings.storage) as repository,
        ):
            fetcher = MailFetcher(
                mailbox=mailbox,
                repository=repository,
                parser=email_parser,
                batch_size=settings.sync.batch_size,
                max_messages=settings.sync.max_messages,
                insight_service=insight_service,
                drafting_service=drafting_service,
                follow_up_planner=follow_up_planner,
            )
            result = fetcher.run()
    except ImapError as exc:
        return SyncOutcome(success=False, message=f"Sync failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface unexpected failure to UI
        return SyncOutcome(success=False, message=f"Sync failed: {exc}")

    processed = result.processed
    if processed == 0:
        return SyncOutcome(
            success=True,
            message="Sync complete. No new messages processed.",
        )
    return SyncOutcome(
        success=True,
        message=f"Sync complete. Processed {processed} message(s).",
    )


def _delete_email(settings: AppSettings, uid: int) -> DeleteOutcome:
    missing_credentials = not settings.imap.username or not settings.imap.app_password
    if missing_credentials:
        return DeleteOutcome(
            success=False,
            message="Configure IMAP username and app password before deleting.",
        )

    try:
        with (
            ImapClient(settings.imap) as mailbox,
            SqliteEmailRepository(settings.storage) as repository,
        ):
            mailbox.delete(uid)
            removed = repository.delete_email(uid)
    except ImapError as exc:
        return DeleteOutcome(success=False, message=f"Delete failed: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface unexpected failure to UI
        return DeleteOutcome(success=False, message=f"Delete failed: {exc}")

    if removed:
        return DeleteOutcome(success=True, message=f"Message UID {uid} deleted.")
    return DeleteOutcome(
        success=True,
        message=f"Message UID {uid} deleted (no local record found).",
    )


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
