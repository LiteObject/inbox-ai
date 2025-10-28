"""SQLite-backed email repository implementation."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import cast

from ..core.config import StorageSettings
from ..core.interfaces import EmailRepository
from ..core.models import (
    AttachmentMeta,
    DraftRecord,
    EmailBody,
    EmailEnvelope,
    EmailInsight,
    FollowUpTask,
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
            db_path,
            detect_types=sqlite3.PARSE_DECLTYPES,
            check_same_thread=False,
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

    def fetch_email(self, uid: int) -> EmailEnvelope | None:
        """Retrieve a stored email."""
        cur = self._connection.execute(
            """
            SELECT
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
            FROM emails
            WHERE uid = ?
            """,
            (uid,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        attachments = self._load_attachments(uid)
        return EmailEnvelope(
            uid=row["uid"],
            message_id=row["message_id"],
            thread_id=row["thread_id"],
            subject=row["subject"],
            sender=row["sender"],
            to=_split_recipients(row["to_recipients"]),
            cc=_split_recipients(row["cc_recipients"]),
            bcc=_split_recipients(row["bcc_recipients"]),
            sent_at=_parse_datetime(row["sent_at"]),
            received_at=_parse_datetime(row["received_at"]),
            body=EmailBody(text=row["body_text"], html=row["body_html"]),
            attachments=attachments,
        )

    def delete_email(self, uid: int) -> bool:
        """Delete the stored email and cascading metadata."""
        LOGGER.debug("Deleting email UID %s", uid)
        with self._connection:
            cur = self._connection.execute(
                "DELETE FROM emails WHERE uid = ?",
                (uid,),
            )
        return cur.rowcount > 0

    def fetch_insight(self, email_uid: int) -> EmailInsight | None:
        """Fetch the stored insight row for the supplied email UID."""
        cur = self._connection.execute(
            """
            SELECT summary, action_items, priority_score, provider, generated_at, used_fallback
            FROM email_insights
            WHERE email_uid = ?
            """,
            (email_uid,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        action_items_raw = row["action_items"] or "[]"
        action_items = tuple(json.loads(action_items_raw))
        return EmailInsight(
            email_uid=email_uid,
            summary=row["summary"],
            action_items=tuple(str(item) for item in action_items),
            priority=row["priority_score"],
            provider=row["provider"],
            generated_at=cast(
                datetime, _parse_datetime(row["generated_at"], assume_utc=True)
            ),
            used_fallback=bool(row["used_fallback"]),
        )

    def persist_draft(self, draft: DraftRecord) -> DraftRecord:
        """Insert a new draft row and return the stored record with identifier."""
        LOGGER.debug("Persisting draft for UID %s", draft.email_uid)
        with self._connection:
            cur = self._connection.execute(
                """
                INSERT INTO drafts (
                    email_uid,
                    body,
                    provider,
                    generated_at,
                    confidence,
                    used_fallback
                ) VALUES (?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    draft.email_uid,
                    draft.body,
                    draft.provider,
                    draft.generated_at.isoformat(),
                    draft.confidence,
                    1 if draft.used_fallback else 0,
                ),
            )
            row = cur.fetchone()
            draft_id = row[0] if row is not None else None
        return DraftRecord(
            id=draft_id,
            email_uid=draft.email_uid,
            body=draft.body,
            provider=draft.provider,
            generated_at=draft.generated_at,
            confidence=draft.confidence,
            used_fallback=draft.used_fallback,
        )

    def list_recent_insights(
        self,
        limit: int,
        *,
        min_priority: int | None = None,
        max_priority: int | None = None,
    ) -> list[tuple[EmailEnvelope, EmailInsight]]:
        """Return recent email/insight pairs ordered by newest insight first."""
        query = [
            """
            SELECT
                e.uid,
                e.message_id,
                e.thread_id,
                e.subject,
                e.sender,
                e.to_recipients,
                e.cc_recipients,
                e.bcc_recipients,
                e.sent_at,
                e.received_at,
                e.body_text,
                e.body_html,
                i.summary,
                i.action_items,
                i.priority_score,
                i.provider,
                i.generated_at,
                i.used_fallback
            FROM email_insights i
            INNER JOIN emails e ON e.uid = i.email_uid
            """
        ]
        params: list[object] = []
        conditions: list[str] = []
        if min_priority is not None:
            conditions.append("i.priority_score >= ?")
            params.append(min_priority)
        if max_priority is not None:
            conditions.append("i.priority_score <= ?")
            params.append(max_priority)
        if conditions:
            query.append("WHERE ")
            query.append(" AND ".join(conditions))
        query.append(" ORDER BY i.generated_at DESC LIMIT ?")
        params.append(limit)
        cur = self._connection.execute("".join(query), params)
        results: list[tuple[EmailEnvelope, EmailInsight]] = []
        for row in cur.fetchall():
            uid = row["uid"]
            email = EmailEnvelope(
                uid=uid,
                message_id=row["message_id"],
                thread_id=row["thread_id"],
                subject=row["subject"],
                sender=row["sender"],
                to=_split_recipients(row["to_recipients"]),
                cc=_split_recipients(row["cc_recipients"]),
                bcc=_split_recipients(row["bcc_recipients"]),
                sent_at=_parse_datetime(row["sent_at"]),
                received_at=_parse_datetime(row["received_at"]),
                body=EmailBody(text=row["body_text"], html=row["body_html"]),
                attachments=self._load_attachments(uid),
            )
            action_items = tuple(json.loads(row["action_items"] or "[]"))
            insight = EmailInsight(
                email_uid=uid,
                summary=row["summary"],
                action_items=tuple(str(item) for item in action_items),
                priority=row["priority_score"],
                provider=row["provider"],
                generated_at=cast(
                    datetime,
                    _parse_datetime(row["generated_at"], assume_utc=True),
                ),
                used_fallback=bool(row["used_fallback"]),
            )
            results.append((email, insight))
        return results

    def count_insights(self) -> int:
        """Return total number of insight records."""
        cur = self._connection.execute("SELECT COUNT(*) FROM email_insights")
        row = cur.fetchone()
        return int(row[0]) if row is not None else 0

    def list_recent_drafts(self, limit: int) -> list[DraftRecord]:
        """Return recently generated drafts ordered by generation timestamp."""
        cur = self._connection.execute(
            """
            SELECT
                id,
                email_uid,
                body,
                provider,
                generated_at,
                confidence,
                used_fallback
            FROM drafts
            ORDER BY generated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        drafts: list[DraftRecord] = []
        for row in cur.fetchall():
            drafts.append(
                DraftRecord(
                    id=row["id"],
                    email_uid=row["email_uid"],
                    body=row["body"],
                    provider=row["provider"],
                    generated_at=cast(
                        datetime, _parse_datetime(row["generated_at"], assume_utc=True)
                    ),
                    confidence=row["confidence"],
                    used_fallback=bool(row["used_fallback"]),
                )
            )
        return drafts

    def fetch_latest_drafts(self, uids: Sequence[int]) -> dict[int, DraftRecord]:
        """Return the most recent draft for each UID in ``uids``."""
        if not uids:
            return {}
        unique_uids = tuple(dict.fromkeys(uids))
        placeholders = ",".join("?" for _ in unique_uids)
        query = f"""
            SELECT d.id, d.email_uid, d.body, d.provider, d.generated_at, d.confidence, d.used_fallback
            FROM drafts AS d
            INNER JOIN (
                SELECT email_uid, MAX(generated_at) AS max_generated_at
                FROM drafts
                WHERE email_uid IN ({placeholders})
                GROUP BY email_uid
            ) AS latest
            ON latest.email_uid = d.email_uid AND latest.max_generated_at = d.generated_at
        """
        cur = self._connection.execute(query, unique_uids)
        results: dict[int, DraftRecord] = {}
        for row in cur.fetchall():
            uid = row["email_uid"]
            results[uid] = DraftRecord(
                id=row["id"],
                email_uid=uid,
                body=row["body"],
                provider=row["provider"],
                generated_at=cast(
                    datetime, _parse_datetime(row["generated_at"], assume_utc=True)
                ),
                confidence=row["confidence"],
                used_fallback=bool(row["used_fallback"]),
            )
        return results

    def replace_follow_ups(self, email_uid: int, tasks: Sequence[FollowUpTask]) -> None:
        """Replace existing follow-ups for the email with the provided sequence."""
        LOGGER.debug("Replacing follow-ups for UID %s", email_uid)
        with self._connection:
            self._connection.execute(
                "DELETE FROM follow_ups WHERE email_uid = ?", (email_uid,)
            )
            for task in tasks:
                self._connection.execute(
                    """
                    INSERT INTO follow_ups (
                        email_uid,
                        action,
                        due_at,
                        status,
                        created_at,
                        completed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        email_uid,
                        task.action,
                        task.due_at.isoformat() if task.due_at else None,
                        task.status,
                        task.created_at.isoformat(),
                        task.completed_at.isoformat() if task.completed_at else None,
                    ),
                )

    def list_follow_ups(
        self, *, status: str | None = None, limit: int | None = None
    ) -> list[FollowUpTask]:
        """Return follow-ups filtered by status and limit, ordered by due/created date."""
        query = """
            SELECT id, email_uid, action, due_at, status, created_at, completed_at
            FROM follow_ups
            {where}
            ORDER BY
                CASE WHEN due_at IS NULL THEN 1 ELSE 0 END,
                due_at ASC,
                created_at ASC
            {limit}
            """
        where_clause = ""
        parameters: list[object] = []
        if status:
            where_clause = "WHERE status = ?"
            parameters.append(status)
        limit_clause = ""
        if limit is not None:
            limit_clause = "LIMIT ?"
            parameters.append(limit)
        formatted_query = query.format(where=where_clause, limit=limit_clause)
        cur = self._connection.execute(formatted_query, tuple(parameters))
        items: list[FollowUpTask] = []
        for row in cur.fetchall():
            items.append(
                FollowUpTask(
                    id=row["id"],
                    email_uid=row["email_uid"],
                    action=row["action"],
                    due_at=_parse_datetime(row["due_at"]),
                    status=row["status"],
                    created_at=cast(
                        datetime,
                        _parse_datetime(row["created_at"], assume_utc=True),
                    ),
                    completed_at=_parse_datetime(row["completed_at"], assume_utc=True),
                )
            )
        return items

    def update_follow_up_status(self, follow_up_id: int, status: str) -> None:
        """Update the status (and completion timestamp) for a follow-up entry."""
        completed_at = datetime.now(tz=UTC) if status == "done" else None
        with self._connection:
            self._connection.execute(
                """
                UPDATE follow_ups
                SET status = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    status,
                    completed_at.isoformat() if completed_at else None,
                    follow_up_id,
                ),
            )

    def _load_attachments(self, email_uid: int) -> tuple[AttachmentMeta, ...]:
        cur = self._connection.execute(
            "SELECT filename, content_type, size FROM attachments WHERE email_uid = ?",
            (email_uid,),
        )
        return tuple(
            AttachmentMeta(
                filename=row["filename"],
                content_type=row["content_type"],
                size=row["size"],
            )
            for row in cur.fetchall()
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


def _parse_datetime(value: str | None, *, assume_utc: bool = False) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None and assume_utc:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _split_recipients(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(
        part for part in (segment.strip() for segment in value.split(",")) if part
    )


__all__ = ["SqliteEmailRepository"]
