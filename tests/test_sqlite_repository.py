"""Tests for the SQLite-backed email repository."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from inbox_ai.core.config import StorageSettings
from inbox_ai.core.models import (
    AttachmentMeta,
    DraftRecord,
    EmailBody,
    EmailEnvelope,
    EmailInsight,
    FollowUpTask,
    SyncCheckpoint,
    ThreadSummary,
)
from inbox_ai.storage import SqliteEmailRepository


def _sample_envelope(uid: int) -> EmailEnvelope:
    timestamp = datetime(2025, 10, 24, 15, 0, tzinfo=timezone.utc)
    return EmailEnvelope(
        uid=uid,
        mailbox="INBOX",
        message_id=f"<{uid}@example.com>",
        thread_id="thread-1",
        subject="Demo",
        sender="sender@example.com",
        to=("user@example.com",),
        cc=(),
        bcc=(),
        sent_at=timestamp,
        received_at=timestamp,
        body=EmailBody(text="Hello", html=None),
        attachments=(
            AttachmentMeta(filename="note.txt", content_type="text/plain", size=5),
        ),
    )


def test_repository_persists_email_and_attachments(tmp_path: Path) -> None:
    db_path = tmp_path / "inbox.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    envelope = _sample_envelope(uid=10)
    repository.persist_email(envelope)
    repository.close()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT subject, sender, body_text FROM emails WHERE uid = ?",
            (10,),
        ).fetchone()
        assert row is not None
        assert row["subject"] == "Demo"
        assert row["sender"] == "sender@example.com"
        assert row["body_text"] == "Hello"

        attachment_row = conn.execute(
            "SELECT filename, size FROM attachments WHERE email_uid = ?",
            (10,),
        ).fetchone()
        assert attachment_row is not None
        assert attachment_row["filename"] == "note.txt"
        assert attachment_row["size"] == 5


def test_repository_checkpoint_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoint.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    assert repository.get_checkpoint("INBOX") is None

    checkpoint = SyncCheckpoint(mailbox="INBOX", last_uid=42)
    repository.upsert_checkpoint(checkpoint)

    restored = repository.get_checkpoint("INBOX")
    assert restored == checkpoint
    repository.close()


def test_repository_persists_insights(tmp_path: Path) -> None:
    db_path = tmp_path / "insights.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.persist_email(_sample_envelope(uid=99))
    generated_at = datetime(2025, 10, 26, 8, 0, tzinfo=timezone.utc)
    insight = EmailInsight(
        email_uid=99,
        summary="Summary text",
        action_items=("Reply soon", "Schedule meeting"),
        priority=7,
        provider="test-provider",
        generated_at=generated_at,
        used_fallback=True,
    )

    repository.persist_insight(insight)
    repository.close()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT summary, action_items, priority_score, provider, used_fallback FROM email_insights WHERE email_uid = ?",
            (99,),
        ).fetchone()
        assert row is not None
        assert row["summary"] == "Summary text"
        assert json.loads(row["action_items"]) == ["Reply soon", "Schedule meeting"]
        assert row["priority_score"] == 7
        assert row["provider"] == "test-provider"
        assert row["used_fallback"] == 1


def test_repository_persists_feedback_and_thread_context(tmp_path: Path) -> None:
    db_path = tmp_path / "feedback.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)

    first_email = _sample_envelope(uid=11)
    second_email = _sample_envelope(uid=12)
    repository.persist_email(first_email)
    repository.persist_email(second_email)
    repository.persist_insight(
        EmailInsight(
            email_uid=11,
            summary="Initial thread summary",
            action_items=("Reply",),
            priority=6,
            provider="test",
            generated_at=datetime(2025, 10, 26, 8, 0, tzinfo=timezone.utc),
            used_fallback=False,
        )
    )

    draft = repository.persist_draft(
        DraftRecord(
            id=None,
            email_uid=12,
            body="Draft reply",
            provider="test",
            generated_at=datetime(2025, 10, 26, 9, 0, tzinfo=timezone.utc),
            confidence=0.9,
            used_fallback=False,
        )
    )
    assert draft.id is not None

    assert repository.set_insight_rating(11, 1) is True
    assert repository.set_draft_rating(draft.id, 12, -1) is True
    rated_insight = repository.fetch_insight(11)
    assert rated_insight is not None
    assert rated_insight.user_rating == 1

    updated_draft = repository.update_draft_body(
        draft.id,
        12,
        body="Draft reply edited",
        provider="manual-edit",
        generated_at=datetime(2025, 10, 26, 9, 30, tzinfo=timezone.utc),
        confidence=None,
        used_fallback=False,
        user_edited=True,
    )
    assert updated_draft is not None
    assert updated_draft.user_rating == -1
    assert updated_draft.user_edited is True

    thread_history = repository.list_thread_emails("thread-1", exclude_uid=12)
    assert thread_history == (
        ThreadSummary(
            email_uid=11,
            subject="Demo",
            sender="sender@example.com",
            summary="Initial thread summary",
        ),
    )

    assert repository.mark_draft_sent(draft.id) is True
    assert repository.delete_draft(draft.id, 12) is True
    assert repository.fetch_draft(draft.id) is None

    metrics = repository.get_feedback_metrics()
    assert metrics["insight_positive"] == 1
    assert metrics["draft_negative"] == 1
    assert metrics["draft_edited"] == 1
    assert metrics["draft_sent"] == 1
    assert metrics["draft_deleted"] == 1
    repository.close()


def test_repository_reopen_skips_duplicate_column_migration_warnings(
    tmp_path: Path, caplog
) -> None:
    db_path = tmp_path / "reopen.db"
    settings = StorageSettings(db_path=db_path)

    first_repository = SqliteEmailRepository(settings)
    first_repository.close()

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        second_repository = SqliteEmailRepository(settings)
        second_repository.close()

    warning_messages = [record.getMessage() for record in caplog.records]
    assert all("009_sent_drafts.sql" not in message for message in warning_messages)
    assert all("010_calendar_sync.sql" not in message for message in warning_messages)


def test_repository_persists_drafts(tmp_path: Path) -> None:
    db_path = tmp_path / "drafts.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.persist_email(_sample_envelope(uid=55))
    generated_at = datetime(2025, 10, 26, 9, 30, tzinfo=timezone.utc)
    draft = DraftRecord(
        id=None,
        email_uid=55,
        body="Thanks for the update.",
        provider="test",
        generated_at=generated_at,
        confidence=0.7,
        used_fallback=False,
    )

    stored = repository.persist_draft(draft)
    repository.close()

    assert stored.id is not None

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT body, provider, confidence, used_fallback FROM drafts WHERE email_uid = ?",
            (55,),
        ).fetchone()
        assert row is not None
        assert row["body"] == "Thanks for the update."
        assert row["provider"] == "test"
        assert row["confidence"] == 0.7
        assert row["used_fallback"] == 0


def test_repository_replaces_follow_ups(tmp_path: Path) -> None:
    db_path = tmp_path / "followups.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.persist_email(_sample_envelope(uid=77))
    created_at = datetime(2025, 10, 26, 10, 0, tzinfo=timezone.utc)
    due_at = created_at + timedelta(days=2)
    initial_tasks = (
        FollowUpTask(
            id=None,
            email_uid=77,
            action="Send notes",
            due_at=due_at,
            status="open",
            created_at=created_at,
            completed_at=None,
        ),
        FollowUpTask(
            id=None,
            email_uid=77,
            action="Book meeting",
            due_at=None,
            status="open",
            created_at=created_at,
            completed_at=None,
        ),
    )
    repository.replace_follow_ups(77, initial_tasks)

    revised_tasks = (
        FollowUpTask(
            id=None,
            email_uid=77,
            action="Send summary",
            due_at=due_at,
            status="open",
            created_at=created_at,
            completed_at=None,
        ),
    )
    repository.replace_follow_ups(77, revised_tasks)
    repository.close()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT action, due_at FROM follow_ups WHERE email_uid = ?",
            (77,),
        ).fetchall()
        assert len(rows) == 1
    assert rows[0]["action"] == "Send summary"
    assert datetime.fromisoformat(rows[0]["due_at"]) == due_at


def test_repository_lists_and_updates_follow_ups(tmp_path: Path) -> None:
    db_path = tmp_path / "followups_status.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.persist_email(_sample_envelope(uid=88))
    created_at = datetime(2025, 10, 26, 11, 0, tzinfo=timezone.utc)
    task = FollowUpTask(
        id=None,
        email_uid=88,
        action="Review contract",
        due_at=created_at + timedelta(days=1),
        status="open",
        created_at=created_at,
        completed_at=None,
    )
    repository.replace_follow_ups(88, (task,))

    open_tasks = repository.list_follow_ups(status="open")
    assert len(open_tasks) == 1
    stored_task = open_tasks[0]
    assert stored_task.id is not None
    assert stored_task.action == "Review contract"

    repository.update_follow_up_status(stored_task.id, "done")
    done_tasks = repository.list_follow_ups(status="done")
    assert len(done_tasks) == 1
    updated_task = done_tasks[0]
    assert updated_task.status == "done"
    assert updated_task.completed_at is not None
    repository.close()


def test_repository_lists_recent_drafts(tmp_path: Path) -> None:
    db_path = tmp_path / "drafts_list.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.persist_email(_sample_envelope(uid=1))
    repository.persist_email(_sample_envelope(uid=2))
    base_time = datetime(2025, 10, 26, 12, 0, tzinfo=timezone.utc)
    for idx, uid in enumerate((1, 2), start=1):
        draft = DraftRecord(
            id=None,
            email_uid=uid,
            body=f"Draft {uid}",
            provider="test",
            generated_at=base_time + timedelta(minutes=idx),
            confidence=None,
            used_fallback=False,
        )
        repository.persist_draft(draft)

    drafts = repository.list_recent_drafts(limit=5)
    repository.close()

    assert [draft.email_uid for draft in drafts] == [2, 1]
    assert drafts[0].generated_at.tzinfo is not None


def test_repository_updates_draft_body(tmp_path: Path) -> None:
    db_path = tmp_path / "drafts_update.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.persist_email(_sample_envelope(uid=42))

    original_time = datetime(2025, 10, 26, 13, 0, tzinfo=timezone.utc)
    stored = repository.persist_draft(
        DraftRecord(
            id=None,
            email_uid=42,
            body="Initial draft body",
            provider="llm",
            generated_at=original_time,
            confidence=0.75,
            used_fallback=True,
        )
    )
    assert stored.id is not None

    new_time = original_time + timedelta(minutes=30)
    updated = repository.update_draft_body(
        stored.id,
        42,
        body="Refined response",
        provider="manual-edit",
        generated_at=new_time,
        confidence=None,
        used_fallback=False,
        user_edited=True,
    )

    assert updated is not None
    assert updated.body == "Refined response"
    assert updated.provider == "manual-edit"
    assert updated.generated_at == new_time
    assert updated.confidence is None
    assert updated.used_fallback is False
    assert updated.user_edited is True

    latest = repository.fetch_latest_drafts([42])
    assert latest[42].body == "Refined response"
    repository.close()


def test_repository_deletes_draft(tmp_path: Path) -> None:
    db_path = tmp_path / "drafts_delete.db"
    settings = StorageSettings(db_path=db_path)
    repository = SqliteEmailRepository(settings)
    repository.persist_email(_sample_envelope(uid=5))

    stored = repository.persist_draft(
        DraftRecord(
            id=None,
            email_uid=5,
            body="Draft to remove",
            provider="test",
            generated_at=datetime(2025, 10, 26, 9, 0, tzinfo=timezone.utc),
            confidence=None,
            used_fallback=False,
        )
    )
    assert stored.id is not None

    deleted = repository.delete_draft(stored.id, 5)
    assert deleted is True

    latest = repository.fetch_latest_drafts([5])
    assert 5 not in latest
    repository.close()
