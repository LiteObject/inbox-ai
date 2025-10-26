"""Protocol interfaces for decoupling components."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from .models import EmailEnvelope, MessageChunk, SyncCheckpoint


class MailboxProvider(Protocol):
    """Abstraction over an email source such as IMAP."""

    mailbox: str

    def fetch_since(
        self, last_uid: int | None, batch_size: int
    ) -> Iterable[MessageChunk]:
        """Yield messages with UID greater than the provided checkpoint."""
        raise NotImplementedError

    def close(self) -> None:
        """Release any network resources."""
        raise NotImplementedError


class EmailRepository(Protocol):
    """Abstraction for email persistence."""

    def persist_email(self, email: EmailEnvelope) -> None:
        """Store a normalized email instance."""
        raise NotImplementedError

    def get_checkpoint(self, mailbox: str) -> SyncCheckpoint | None:
        """Return the last stored checkpoint for the given mailbox."""
        raise NotImplementedError

    def upsert_checkpoint(self, checkpoint: SyncCheckpoint) -> None:
        """Persist the latest checkpoint for a mailbox."""
        raise NotImplementedError

    def close(self) -> None:
        """Close database connections if necessary."""
        raise NotImplementedError


__all__ = [
    "EmailRepository",
    "MailboxProvider",
]
