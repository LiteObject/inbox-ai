"""Integration tests for the FastAPI web application."""

from __future__ import annotations

import importlib
import os
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlsplit

from fastapi.testclient import TestClient

from inbox_ai.calendar.google_calendar_client import CalendarAuthError
from inbox_ai.core.config import (
    AppSettings,
    CalendarSettings,
    ImapSettings,
    LlmSettings,
    StorageSettings,
)
from inbox_ai.core.models import (
    DraftRecord,
    EmailBody,
    EmailEnvelope,
    EmailInsight,
    FollowUpTask,
)
from inbox_ai.storage import SqliteEmailRepository
from inbox_ai.web import create_app
from inbox_ai.web.app import CONFIG_FIELD_KEYS, DeleteOutcome
from inbox_ai.web.security import CSRF_COOKIE_NAME, CSRF_FIELD_NAME

web_app_module = importlib.import_module("inbox_ai.web.app")


def _seed_data(repository: SqliteEmailRepository) -> int:
    envelope = EmailEnvelope(
        uid=1,
        mailbox="INBOX",
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
    assert payload["filters"]["followStatus"] == "all"

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

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    response = client.post(
        f"/follow-ups/{follow_up_id}/status",
        data={
            "status": "done",
            "redirect_to": "/?follow_status=done",
            CSRF_FIELD_NAME: csrf_token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/?follow_status=done"

    with SqliteEmailRepository(settings) as verification_repo:
        done_tasks = verification_repo.list_follow_ups(status="done")
        assert done_tasks and done_tasks[0].id == follow_up_id

    html_response = client.get("/?follow_status=done")
    assert html_response.status_code == 200
    assert ">done</span>" in html_response.text

    api_response = client.get("/api/dashboard?follow_status=done")
    assert api_response.status_code == 200
    api_payload = api_response.json()
    assert api_payload["filters"]["followStatus"] == "done"
    assert api_payload["followUps"] and api_payload["followUps"][0]["status"] == "done"


def test_delete_follow_up_api_removes_task(tmp_path) -> None:
    db_path = tmp_path / "web_followup_delete.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    follow_up_id = _seed_data(repository)
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    response = client.delete(
        f"/api/follow-ups/{follow_up_id}",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "follow_up_id": follow_up_id,
        "message": "Follow-up deleted.",
    }

    with SqliteEmailRepository(settings) as verification_repo:
        assert verification_repo.list_follow_ups() == []


def test_delete_email_api_returns_json(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "web_delete_api.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    def fake_delete_email(
        _settings: AppSettings, uid: int, _repository: object
    ) -> DeleteOutcome:
        return DeleteOutcome(success=True, message=f"Message UID {uid} deleted.")

    monkeypatch.setattr(web_app_module, "_delete_email", fake_delete_email)

    response = client.delete(
        "/api/emails/1",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "message": "Message UID 1 deleted.",
        "uid": 1,
    }


def test_dashboard_refresh_does_not_show_deleted_email(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "web_delete_refresh.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    initial_response = client.get("/")
    assert initial_response.status_code == 200
    assert "Status update" in initial_response.text

    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    def fake_delete_email(
        _settings: AppSettings, uid: int, repository: SqliteEmailRepository
    ) -> DeleteOutcome:
        deleted = repository.delete_email(uid)
        assert deleted is True
        return DeleteOutcome(success=True, message=f"Message UID {uid} deleted.")

    monkeypatch.setattr(web_app_module, "_delete_email", fake_delete_email)

    delete_response = client.delete(
        "/api/emails/1",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert delete_response.status_code == 200
    assert delete_response.json()["success"] is True

    refreshed_response = client.get("/")
    assert refreshed_response.status_code == 200
    assert "Status update" not in refreshed_response.text


def test_manual_sync_endpoint_handles_missing_credentials(tmp_path) -> None:
    db_path = tmp_path / "web_sync.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    response = client.post(
        "/sync",
        data={"redirect_to": "/", CSRF_FIELD_NAME: csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 303
    location = response.headers["location"]
    assert "sync_status=error" in location

    html_response = client.get(location)
    assert html_response.status_code == 200
    assert "Configure IMAP username" in html_response.text


def test_dashboard_accepts_manual_draft_edits(tmp_path) -> None:
    db_path = tmp_path / "web_draft_edit.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    drafts = repository.list_recent_drafts(limit=1)
    assert drafts
    draft = drafts[0]
    assert draft.id is not None
    original_generated = draft.generated_at
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    updated_body = "Appreciate the update. We'll respond soon."
    response = client.post(
        "/emails/1/draft",
        data={
            "body": updated_body,
            "draft_id": str(draft.id),
            "provider": "manual-edit",
            "redirect_to": "/",
            CSRF_FIELD_NAME: csrf_token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "draft_status=ok" in location

    with SqliteEmailRepository(settings) as verification_repo:
        latest = verification_repo.fetch_latest_drafts([1])
        assert 1 in latest
        updated = latest[1]
        assert updated.body == updated_body
        assert updated.provider == "manual-edit"
        assert updated.user_edited is True
        assert updated.generated_at > original_generated


def test_dashboard_deletes_draft(tmp_path) -> None:
    db_path = tmp_path / "web_draft_delete.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    drafts = repository.list_recent_drafts(limit=1)
    assert drafts
    draft = drafts[0]
    assert draft.id is not None
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    response = client.post(
        "/emails/1/draft/delete",
        data={
            "draft_id": str(draft.id),
            "redirect_to": "/",
            CSRF_FIELD_NAME: csrf_token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "draft_status=ok" in location

    with SqliteEmailRepository(settings) as verification_repo:
        drafts_after = verification_repo.fetch_latest_drafts([1])
        assert 1 not in drafts_after


def test_dashboard_feedback_routes_persist_ratings(tmp_path) -> None:
    db_path = tmp_path / "web_feedback.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    draft = repository.fetch_latest_drafts([1])[1]
    assert draft.id is not None
    repository.close()

    app_settings = AppSettings(storage=settings)
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    insight_response = client.post(
        "/emails/1/insight/rating",
        data={
            "rating": "1",
            "redirect_to": "/",
            CSRF_FIELD_NAME: csrf_token,
        },
        follow_redirects=False,
    )
    assert insight_response.status_code == 303
    assert "feedback_status=ok" in insight_response.headers["location"]

    draft_response = client.post(
        "/emails/1/draft/rating",
        data={
            "draft_id": str(draft.id),
            "rating": "-1",
            "redirect_to": "/",
            CSRF_FIELD_NAME: csrf_token,
        },
        follow_redirects=False,
    )
    assert draft_response.status_code == 303
    assert "feedback_status=ok" in draft_response.headers["location"]

    with SqliteEmailRepository(settings) as verification_repo:
        rated_insight = verification_repo.fetch_insight(1)
        latest_draft = verification_repo.fetch_latest_drafts([1])[1]
        assert rated_insight is not None
        assert rated_insight.user_rating == 1
        assert latest_draft.user_rating == -1


def test_dashboard_regenerates_draft(tmp_path) -> None:
    db_path = tmp_path / "web_draft_regenerate.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    _seed_data(repository)
    existing = repository.fetch_latest_drafts([1])[1]
    assert existing.id is not None
    repository.close()

    app_settings = AppSettings(
        storage=settings,
        llm=LlmSettings(base_url="", model=""),
    )
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    response = client.post(
        "/emails/1/draft/regenerate",
        data={
            "draft_id": str(existing.id),
            "redirect_to": "/",
            CSRF_FIELD_NAME: csrf_token,
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "draft_status=ok" in location

    with SqliteEmailRepository(settings) as verification_repo:
        drafts_after = verification_repo.fetch_latest_drafts([1])
        assert 1 in drafts_after
        regenerated = drafts_after[1]
        assert regenerated.body != existing.body
        assert regenerated.provider == "deterministic"
        assert regenerated.used_fallback is True
        assert regenerated.body.startswith("Hi team")
        assert regenerated.generated_at > existing.generated_at


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
        csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
        assert csrf_token is not None

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
        payload[CSRF_FIELD_NAME] = csrf_token

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


def test_calendar_status_clears_stale_tokens_on_auth_failure(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "web_calendar_status.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.set_user_preference("calendar_access_token", "access-token")
    repository.set_user_preference("calendar_refresh_token", "refresh-token")
    repository.close()

    async def fake_list_calendars(_self) -> list[dict[str, str]]:
        raise CalendarAuthError(
            "Google Calendar authorization expired. Please reconnect."
        )

    monkeypatch.setattr(
        web_app_module.GoogleCalendarClient,
        "list_calendars",
        fake_list_calendars,
    )

    app_settings = AppSettings(
        storage=settings,
        calendar=CalendarSettings(
            enabled=True,
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    app = create_app(app_settings)
    client = TestClient(app)

    response = client.get("/api/calendar/status")

    assert response.status_code == 200
    assert response.json() == {
        "connected": False,
        "configured": True,
        "selected_calendar": "primary",
        "account_email": None,
        "reauth_required": True,
        "error": "Google Calendar authorization expired. Please reconnect.",
    }

    with SqliteEmailRepository(settings) as verification_repo:
        assert verification_repo.get_user_preference("calendar_access_token") is None
        assert verification_repo.get_user_preference("calendar_refresh_token") is None


def test_calendar_status_uses_account_scoped_preferences(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "web_calendar_scoped_status.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.set_user_preference(
        "calendar_access_token:owner@example.com", "access-token"
    )
    repository.set_user_preference(
        "calendar_selected_calendar:owner@example.com", "team-calendar"
    )
    repository.close()

    async def fake_list_calendars(_self) -> list[dict[str, str]]:
        return [
            {"id": "primary", "summary": "Personal"},
            {"id": "team-calendar", "summary": "Team"},
        ]

    monkeypatch.setattr(
        web_app_module.GoogleCalendarClient,
        "list_calendars",
        fake_list_calendars,
    )

    app_settings = AppSettings(
        storage=settings,
        imap=ImapSettings(username="owner@example.com"),
        calendar=CalendarSettings(
            enabled=True,
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    app = create_app(app_settings)
    client = TestClient(app)

    response = client.get("/api/calendar/status")

    assert response.status_code == 200
    assert response.json() == {
        "connected": True,
        "configured": True,
        "selected_calendar": "team-calendar",
        "account_email": "owner@example.com",
        "calendars": [
            {"id": "primary", "summary": "Personal"},
            {"id": "team-calendar", "summary": "Team"},
        ],
    }


def test_calendar_select_persists_selected_calendar_for_current_account(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "web_calendar_select.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.set_user_preference(
        "calendar_access_token:owner@example.com", "access-token"
    )
    repository.set_user_preference(
        "calendar_refresh_token:owner@example.com", "refresh-token"
    )
    repository.close()

    async def fake_list_calendars(_self) -> list[dict[str, str]]:
        return [
            {"id": "primary", "summary": "Personal"},
            {"id": "team-calendar", "summary": "Team"},
        ]

    monkeypatch.setattr(
        web_app_module.GoogleCalendarClient,
        "list_calendars",
        fake_list_calendars,
    )

    app_settings = AppSettings(
        storage=settings,
        imap=ImapSettings(username="owner@example.com"),
        calendar=CalendarSettings(
            enabled=True,
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    response = client.post(
        "/api/calendar/select",
        data={"calendar_id": "team-calendar"},
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "selected_calendar": "team-calendar",
        "selected_calendar_summary": "Team",
        "account_email": "owner@example.com",
    }

    with SqliteEmailRepository(settings) as verification_repo:
        assert (
            verification_repo.get_user_preference(
                "calendar_selected_calendar:owner@example.com"
            )
            == "team-calendar"
        )


def test_calendar_events_return_selected_calendar_items(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "web_calendar_events.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.set_user_preference(
        "calendar_access_token:owner@example.com", "access-token"
    )
    repository.set_user_preference(
        "calendar_refresh_token:owner@example.com", "refresh-token"
    )
    repository.set_user_preference(
        "calendar_selected_calendar:owner@example.com", "team-calendar"
    )
    repository.close()

    captured: dict[str, object] = {}

    async def fake_list_events(self, time_min, time_max, calendar_id=None):
        captured["time_min"] = time_min
        captured["time_max"] = time_max
        captured["calendar_id"] = calendar_id
        return [
            {
                "id": "external-1",
                "summary": "Team offsite",
                "start": {"dateTime": "2026-03-28T15:00:00Z"},
                "end": {"dateTime": "2026-03-28T16:00:00Z"},
                "htmlLink": "https://calendar.google.com/calendar/event?eid=external-1",
                "location": "Conference room",
                "status": "confirmed",
            },
            {
                "id": "cancelled-1",
                "summary": "Cancelled item",
                "start": {"dateTime": "2026-03-29T15:00:00Z"},
                "end": {"dateTime": "2026-03-29T16:00:00Z"},
                "status": "cancelled",
            },
        ]

    monkeypatch.setattr(
        web_app_module.GoogleCalendarClient,
        "list_events",
        fake_list_events,
    )

    app_settings = AppSettings(
        storage=settings,
        imap=ImapSettings(username="owner@example.com"),
        calendar=CalendarSettings(
            enabled=True,
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    app = create_app(app_settings)
    client = TestClient(app)

    response = client.get(
        "/api/calendar/events?start=2026-03-28T00:00:00Z&end=2026-04-01T00:00:00Z"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["configured"] is True
    assert payload["connected"] is True
    assert payload["selected_calendar"] == "team-calendar"
    assert len(payload["events"]) == 1
    assert payload["events"][0]["id"] == "external-1"
    assert payload["events"][0]["summary"] == "Team offsite"
    assert payload["events"][0]["location"] == "Conference room"
    assert payload["events"][0]["eventUrl"] == (
        "https://calendar.google.com/calendar/event?eid=external-1"
    )
    starts_at = datetime.fromisoformat(payload["events"][0]["startsAt"])
    assert starts_at.astimezone(timezone.utc) == datetime(
        2026,
        3,
        28,
        15,
        0,
        tzinfo=timezone.utc,
    )
    assert captured == {
        "time_min": datetime(2026, 3, 28, 0, 0, tzinfo=timezone.utc),
        "time_max": datetime(2026, 4, 1, 0, 0, tzinfo=timezone.utc),
        "calendar_id": "team-calendar",
    }


def test_calendar_events_return_empty_list_when_not_connected(tmp_path) -> None:
    db_path = tmp_path / "web_calendar_events_not_connected.db"
    settings = StorageSettings(db_path=db_path)

    app_settings = AppSettings(
        storage=settings,
        calendar=CalendarSettings(
            enabled=True,
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    app = create_app(app_settings)
    client = TestClient(app)

    response = client.get(
        "/api/calendar/events?start=2026-03-28T00:00:00Z&end=2026-04-01T00:00:00Z"
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "configured": True,
        "connected": False,
        "events": [],
    }


def test_calendar_sync_clears_stale_tokens_on_auth_failure(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "web_calendar_sync.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    follow_up_id = _seed_data(repository)
    repository.set_user_preference("calendar_access_token", "access-token")
    repository.set_user_preference("calendar_refresh_token", "refresh-token")
    repository.close()

    async def fake_create_event(self, **kwargs) -> dict[str, str]:
        raise CalendarAuthError(
            "Google Calendar authorization expired. Please reconnect."
        )

    monkeypatch.setattr(
        web_app_module.GoogleCalendarClient,
        "create_event",
        fake_create_event,
    )

    app_settings = AppSettings(
        storage=settings,
        calendar=CalendarSettings(
            enabled=True,
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    response = client.post(
        f"/api/follow-ups/{follow_up_id}/sync-calendar",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "error": "Google Calendar authorization expired. Please reconnect.",
        "reauth_required": True,
        "connect_url": "/settings#calendar",
    }

    with SqliteEmailRepository(settings) as verification_repo:
        assert verification_repo.get_user_preference("calendar_access_token") is None
        assert verification_repo.get_user_preference("calendar_refresh_token") is None


def test_calendar_sync_returns_settings_url_when_not_connected(tmp_path) -> None:
    db_path = tmp_path / "web_calendar_not_connected.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    follow_up_id = _seed_data(repository)
    repository.close()

    app_settings = AppSettings(
        storage=settings,
        calendar=CalendarSettings(
            enabled=True,
            client_id="client-id",
            client_secret="client-secret",
        ),
    )
    app = create_app(app_settings)
    client = TestClient(app)

    client.get("/")
    csrf_token = client.cookies.get(CSRF_COOKIE_NAME)
    assert csrf_token is not None

    response = client.post(
        f"/api/follow-ups/{follow_up_id}/sync-calendar",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 200
    assert response.json() == {
        "success": False,
        "error": "Not connected to Google Calendar. Please connect in settings.",
        "connect_url": "/settings#calendar",
    }


def test_calendar_callback_encodes_error_redirect(tmp_path) -> None:
    db_path = tmp_path / "web_calendar_callback.db"
    settings = StorageSettings(db_path=db_path)

    app = create_app(AppSettings(storage=settings))
    client = TestClient(app)

    response = client.get(
        "/calendar/callback?error=access_denied%26next%3Dhttps%3A%2F%2Fevil.example",
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    parsed = urlsplit(location)
    params = dict(parse_qsl(parsed.query, keep_blank_values=True))

    assert parsed.path == "/settings"
    assert parsed.fragment == "calendar"
    assert params == {
        "config_status": "calendar_auth_failed",
        "error": "access_denied&next=https://evil.example",
    }
