"""Integration tests for the FastAPI web application."""

from __future__ import annotations

import os
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
from inbox_ai.web.app import CONFIG_FIELD_KEYS


def _seed_data(repository: SqliteEmailRepository) -> int:
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
    stored = repository.list_follow_ups(status="open")
    assert stored and stored[0].id is not None
    return stored[0].id


def test_dashboard_endpoints_return_data(tmp_path) -> None:
    db_path = tmp_path / "web.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    follow_up_id = _seed_data(repository)
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    response = client.get("/api/dashboard")
    assert response.status_code == 200
    payload = response.json()
    assert payload["insights"][0]["uid"] == 1
    assert payload["insights"][0]["priorityLabel"] == "Normal"
    assert payload["drafts"][0]["emailUid"] == 1
    assert payload["followUps"][0]["action"] == "Review notes"
    assert payload["filters"]["followStatus"] == "open"

    html_response = client.get("/")
    assert html_response.status_code == 200
    assert "Inbox AI Dashboard" in html_response.text
    assert "Normal" in html_response.text

    # follow-up ID is returned for subsequent tests to use
    assert follow_up_id > 0


def test_follow_up_actions_and_filters(tmp_path) -> None:
    db_path = tmp_path / "web_actions.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    follow_up_id = _seed_data(repository)
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    response = client.post(
        f"/follow-ups/{follow_up_id}/status",
        data={"status": "done", "redirect_to": "/?follow_status=done"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?follow_status=done"

    with SqliteEmailRepository(settings) as verification_repo:
        done_tasks = verification_repo.list_follow_ups(status="done")
        assert done_tasks and done_tasks[0].id == follow_up_id

    html_response = client.get("/?follow_status=done")
    assert html_response.status_code == 200
    assert "Status: done" in html_response.text

    api_response = client.get("/api/dashboard?follow_status=done")
    assert api_response.status_code == 200
    api_payload = api_response.json()
    assert api_payload["filters"]["followStatus"] == "done"
    assert api_payload["followUps"] and api_payload["followUps"][0]["status"] == "done"


def test_manual_sync_endpoint_handles_missing_credentials(tmp_path) -> None:
    db_path = tmp_path / "web_sync.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    response = client.post(
        "/sync",
        data={"redirect_to": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "sync_status=error" in location

    html_response = client.get(location)
    assert html_response.status_code == 200
    assert "Configure IMAP username" in html_response.text


def test_config_editor_updates_env_file(tmp_path) -> None:
    db_path = tmp_path / "web_config.db"
    env_file = tmp_path / "override.env"
    env_file.write_text("INBOX_AI_IMAP__HOST=imap.gmail.com\n", encoding="utf-8")

    override_var = "INBOX_AI_DASHBOARD_ENV_FILE"
    original_override = os.environ.get(override_var)
    original_values = {key: os.environ.get(key) for key in CONFIG_FIELD_KEYS}
    os.environ[override_var] = str(env_file)

    try:
        settings = StorageSettings(db_path=db_path)
        repository = SqliteEmailRepository(settings)
        _seed_data(repository)
        repository.close()

        app_settings = AppSettings(storage=settings)
        app = create_app(app_settings)
        client = TestClient(app)

        get_response = client.get("/")
        assert get_response.status_code == 200
        assert "Configuration" in get_response.text

        payload = {
            "redirect_to": "/",
            "INBOX_AI_IMAP__HOST": "imap.example.com",
            "INBOX_AI_IMAP__PORT": "995",
            "INBOX_AI_IMAP__USERNAME": "user@example.com",
            "INBOX_AI_IMAP__APP_PASSWORD": "super secret value",
            "INBOX_AI_IMAP__MAILBOX": "INBOX",
            "INBOX_AI_IMAP__USE_SSL": "true",
            "INBOX_AI_LLM__BASE_URL": "http://localhost:11435",
            "INBOX_AI_LLM__MODEL": "gpt-oss:latest",
            "INBOX_AI_LLM__TIMEOUT_SECONDS": "45",
            "INBOX_AI_LLM__TEMPERATURE": "0.4",
            "INBOX_AI_LLM__MAX_OUTPUT_TOKENS": "768",
            "INBOX_AI_LLM__FALLBACK_ENABLED": "false",
            "INBOX_AI_STORAGE__DB_PATH": str(db_path),
            "INBOX_AI_SYNC__BATCH_SIZE": "60",
            "INBOX_AI_SYNC__MAX_MESSAGES": "1000",
            "INBOX_AI_LOGGING__LEVEL": "DEBUG",
            "INBOX_AI_LOGGING__STRUCTURED": "true",
            "INBOX_AI_FOLLOW_UP__DEFAULT_DUE_DAYS": "3",
            "INBOX_AI_FOLLOW_UP__PRIORITY_DUE_DAYS": "1",
            "INBOX_AI_FOLLOW_UP__PRIORITY_THRESHOLD": "6",
        }

        response = client.post("/config", data=payload, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"].endswith("config_status=saved")

        contents = env_file.read_text(encoding="utf-8")
        assert "INBOX_AI_IMAP__HOST=imap.example.com" in contents
        assert 'INBOX_AI_IMAP__APP_PASSWORD="super secret value"' in contents
        assert "INBOX_AI_LLM__FALLBACK_ENABLED=false" in contents

        # Environment variables are updated so subsequent loads read fresh values.
        assert os.environ["INBOX_AI_IMAP__HOST"] == "imap.example.com"
        assert os.environ["INBOX_AI_LLM__FALLBACK_ENABLED"] == "false"
    finally:
        if original_override is None:
            os.environ.pop(override_var, None)
        else:
            os.environ[override_var] = original_override

        for key, value in original_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
