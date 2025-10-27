"""Integration tests for the FastAPI web application."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from inbox_ai.core.config import AppSettings, StorageSettings
from inbox_ai.core.models import (
    DraftRecord,
    EmailBody,
    EmailEnvelope,
    EmailInsight,
    FollowUpTask,
)
from inbox_ai.storage import SqliteEmailRepository
from inbox_ai.web import create_app


def _seed_data(repository: SqliteEmailRepository) -> None:
    envelope = EmailEnvelope(
        uid=1,
        message_id="<1@example.com>",
        thread_id=None,
        subject="Status update",
        sender="team@example.com",
        to=("you@example.com",),
        cc=(),
        bcc=(),
        sent_at=None,
        received_at=None,
        body=EmailBody(text="Body", html=None),
        attachments=(),
    )
    repository.persist_email(envelope)

    generated_at = datetime(2025, 10, 26, 12, 0, tzinfo=timezone.utc)
    insight = EmailInsight(
        email_uid=1,
        summary="Summary",
        action_items=("Do something",),
        priority=6,
        provider="test",
        generated_at=generated_at,
        used_fallback=False,
    )
    repository.persist_insight(insight)

    draft = DraftRecord(
        id=None,
        email_uid=1,
        body="Thanks for the update.",
        provider="test",
        generated_at=generated_at,
        confidence=0.9,
        used_fallback=False,
    )
    repository.persist_draft(draft)

    follow_up = FollowUpTask(
        id=None,
        email_uid=1,
        action="Review notes",
        due_at=generated_at,
        status="open",
        created_at=generated_at,
        completed_at=None,
    )
    repository.replace_follow_ups(1, (follow_up,))


def test_dashboard_endpoints_return_data(tmp_path) -> None:
    db_path = tmp_path / "web.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["insights"][0]["uid"] == 1
    assert payload["drafts"][0]["emailUid"] == 1
    assert payload["followUps"][0]["action"] == "Review notes"

    html_response = client.get("/")
    assert html_response.status_code == 200
    assert "Inbox AI Dashboard" in html_response.text
