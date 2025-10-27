"""Core domain models used across the application."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class AttachmentMeta:
    """Metadata describing an email attachment."""

    filename: str | None
    content_type: str | None
    size: int | None


@dataclass(slots=True)
class EmailBody:
    """Container for textual representations of an email."""

    text: str | None
    html: str | None


# pylint: disable=too-many-instance-attributes
@dataclass(slots=True)
class EmailEnvelope:
    """Normalized email representation ready for persistence."""

    uid: int
    message_id: str | None
    thread_id: str | None
    subject: str | None
    sender: str | None
    to: tuple[str, ...]
    cc: tuple[str, ...]
    bcc: tuple[str, ...]
    sent_at: datetime | None
    received_at: datetime | None
    body: EmailBody
    attachments: tuple[AttachmentMeta, ...]


@dataclass(slots=True)
class MessageChunk:
    """Raw IMAP payload paired with its UID."""

    uid: int
    raw: bytes


@dataclass(slots=True)
class SyncCheckpoint:
    """Last processed UID for a mailbox."""

    mailbox: str
    last_uid: int


@dataclass(slots=True)
class FetchReport:
    """Outcome summary for a mail fetch cycle."""

    processed: int
    new_last_uid: int | None


@dataclass(slots=True)
class EmailInsight:
    """Summary, action items, and priority metadata for an email."""

    email_uid: int
    summary: str
    action_items: tuple[str, ...]
    priority: int
    provider: str
    generated_at: datetime
    used_fallback: bool


__all__ = [
    "AttachmentMeta",
    "EmailBody",
    "EmailEnvelope",
    "MessageChunk",
    "SyncCheckpoint",
    "FetchReport",
    "EmailInsight",
]
