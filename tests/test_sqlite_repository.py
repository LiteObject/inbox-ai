"""Tests for the SQLite-backed email repository."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from inbox_ai.core.config import StorageSettings
from inbox_ai.core.models import (
    AttachmentMeta,
    EmailBody,
    EmailEnvelope,
    SyncCheckpoint,
)
from inbox_ai.storage import SqliteEmailRepository


def _sample_envelope(uid: int) -> EmailEnvelope:
    timestamp = datetime(2025, 10, 24, 15, 0, tzinfo=timezone.utc)
    return EmailEnvelope(
        uid=uid,
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
