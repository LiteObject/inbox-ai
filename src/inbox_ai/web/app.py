"""FastAPI web application exposing Inbox AI data."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.routing import APIRoute
from starlette.templating import Jinja2Templates

from inbox_ai.core import AppSettings, load_app_settings
from inbox_ai.core.models import DraftRecord, EmailEnvelope, EmailInsight, FollowUpTask
from inbox_ai.storage import SqliteEmailRepository

TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app_settings = settings or load_app_settings()
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
        insights = repository.list_recent_insights(limit=20)
        drafts = repository.list_recent_drafts(limit=20)
        follow_ups = repository.list_follow_ups(status="open", limit=20)
        return templates.TemplateResponse(
            request,
            "index.html",
            {
                "insights": [
                    _serialize_insight(email, insight) for email, insight in insights
                ],
                "drafts": [_serialize_draft(draft) for draft in drafts],
                "follow_ups": [_serialize_follow_up(task) for task in follow_ups],
            },
        )

    @app.get("/api/dashboard")
    async def dashboard(
        repository: SqliteEmailRepository = Depends(get_repository),  # noqa: B008
    ) -> dict[str, Any]:
        insights = repository.list_recent_insights(limit=20)
        drafts = repository.list_recent_drafts(limit=20)
        follow_ups = repository.list_follow_ups(status="open", limit=20)
        return {
            "insights": [
                _serialize_insight(email, insight) for email, insight in insights
            ],
            "drafts": [_serialize_draft(draft) for draft in drafts],
            "followUps": [_serialize_follow_up(task) for task in follow_ups],
        }

    _ensure_route_names(app)
    return app


def _ensure_route_names(app: FastAPI) -> None:
    """Assign names to routes if absent for better URL reversing."""
    for route in app.router.routes:
        if isinstance(route, APIRoute) and route.name is None:
            route.name = route.path_format.replace("/", ":") or "root"


def _serialize_insight(email: EmailEnvelope, insight: EmailInsight) -> dict[str, Any]:
    return {
        "uid": email.uid,
        "subject": email.subject,
        "sender": email.sender,
        "summary": insight.summary,
        "actionItems": list(insight.action_items),
        "priority": insight.priority,
        "provider": insight.provider,
        "generatedAt": _isoformat(insight.generated_at),
    }


def _serialize_draft(draft: DraftRecord) -> dict[str, Any]:
    return {
        "id": draft.id,
        "emailUid": draft.email_uid,
        "body": draft.body,
        "provider": draft.provider,
        "confidence": draft.confidence,
        "generatedAt": _isoformat(draft.generated_at),
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
