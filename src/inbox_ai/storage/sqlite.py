"""SQLite-backed email repository implementation."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from types import TracebackType

from ..core.config import StorageSettings
from ..core.interfaces import EmailRepository
from ..core.models import (
    AttachmentMeta,
    EmailEnvelope,
    EmailInsight,
    SyncCheckpoint,
)

LOGGER = logging.getLogger(__name__)


class SqliteEmailRepository(EmailRepository):
    """Persist emails and metadata using SQLite."""

    def __init__(self, settings: StorageSettings) -> None:
        """Initialise the repository and apply migrations."""
        self._settings = settings
        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(
            db_path, detect_types=sqlite3.PARSE_DECLTYPES
        )
        self._connection.row_factory = sqlite3.Row
        self._enable_foreign_keys()
        self._apply_migrations()

    # Context manager helpers -------------------------------------------------
    def __enter__(self) -> SqliteEmailRepository:
        """Enter context manager scope."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Ensure the connection is closed when exiting context manager."""
        self.close()

    # EmailRepository API -----------------------------------------------------
    def persist_email(self, email: EmailEnvelope) -> None:
        """Insert or update the stored record for ``email``."""
        LOGGER.debug("Persisting email UID %s", email.uid)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO emails (
                    uid,
                    message_id,
                    thread_id,
                    subject,
                    sender,
                    to_recipients,
                    cc_recipients,
                    bcc_recipients,
                    sent_at,
                    received_at,
                    body_text,
                    body_html
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uid) DO UPDATE SET
                    message_id=excluded.message_id,
                    thread_id=excluded.thread_id,
                    subject=excluded.subject,
                    sender=excluded.sender,
                    to_recipients=excluded.to_recipients,
                    cc_recipients=excluded.cc_recipients,
                    bcc_recipients=excluded.bcc_recipients,
                    sent_at=excluded.sent_at,
                    received_at=excluded.received_at,
                    body_text=excluded.body_text,
                    body_html=excluded.body_html
                """,
                (
                    email.uid,
                    email.message_id,
                    email.thread_id,
                    email.subject,
                    email.sender,
                    ",".join(email.to),
                    ",".join(email.cc),
                    ",".join(email.bcc),
                    _serialize_datetime(email.sent_at),
                    _serialize_datetime(email.received_at),
                    email.body.text,
                    email.body.html,
                ),
            )

            self._connection.execute(
                "DELETE FROM attachments WHERE email_uid = ?",
                (email.uid,),
            )
            for attachment in email.attachments:
                self._insert_attachment(email.uid, attachment)

    def persist_insight(self, insight: EmailInsight) -> None:
        """Insert or update summarisation data for an email."""
        LOGGER.debug("Persisting insight for UID %s", insight.email_uid)
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO email_insights (
                    email_uid,
                    summary,
                    action_items,
                    priority_score,
                    provider,
                    generated_at,
                    used_fallback
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email_uid) DO UPDATE SET
                    summary=excluded.summary,
                    action_items=excluded.action_items,
                    priority_score=excluded.priority_score,
                    provider=excluded.provider,
                    generated_at=excluded.generated_at,
                    used_fallback=excluded.used_fallback
                """,
                (
                    insight.email_uid,
                    insight.summary,
                    json.dumps(list(insight.action_items)),
                    insight.priority,
                    insight.provider,
                    insight.generated_at.isoformat(),
                    1 if insight.used_fallback else 0,
                ),
            )

    def get_checkpoint(self, mailbox: str) -> SyncCheckpoint | None:
        """Retrieve the last recorded UID for ``mailbox``."""
        cur = self._connection.execute(
            "SELECT mailbox, last_uid FROM sync_state WHERE mailbox = ?",
            (mailbox,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return SyncCheckpoint(mailbox=row["mailbox"], last_uid=row["last_uid"])

    def upsert_checkpoint(self, checkpoint: SyncCheckpoint) -> None:
        """Persist the supplied checkpoint."""
        LOGGER.debug(
            "Updating checkpoint mailbox=%s last_uid=%s",
            checkpoint.mailbox,
            checkpoint.last_uid,
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO sync_state (mailbox, last_uid)
                VALUES (?, ?)
                ON CONFLICT(mailbox) DO UPDATE SET last_uid=excluded.last_uid
                """,
                (checkpoint.mailbox, checkpoint.last_uid),
            )

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._connection.close()

    # Internal helpers --------------------------------------------------------
    def _enable_foreign_keys(self) -> None:
        with self._connection:
            self._connection.execute("PRAGMA foreign_keys = ON")

    def _apply_migrations(self) -> None:
        schema_dir = Path(__file__).resolve().parent / "schema"
        migrations = sorted(schema_dir.glob("*.sql"))
        for migration in migrations:
            LOGGER.debug("Applying migration %s", migration.name)
            script = migration.read_text(encoding="utf-8")
            with self._connection:
                self._connection.executescript(script)

    def _insert_attachment(self, email_uid: int, attachment: AttachmentMeta) -> None:
        self._connection.execute(
            """
            INSERT INTO attachments (email_uid, filename, content_type, size)
            VALUES (?, ?, ?, ?)
            """,
            (email_uid, attachment.filename, attachment.content_type, attachment.size),
        )


def _serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone().isoformat()
    return value.isoformat()


__all__ = ["SqliteEmailRepository"]
