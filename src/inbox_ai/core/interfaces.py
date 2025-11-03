"""Protocol interfaces for decoupling components."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Protocol

from .models import (
    DraftRecord,
    EmailCategory,
    EmailEnvelope,
    EmailInsight,
    FollowUpTask,
    MessageChunk,
    SyncCheckpoint,
)


class InsightError(RuntimeError):
    """Raised when generating insights for an email fails."""


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

    def fetch_email(self, uid: int) -> EmailEnvelope | None:
        """Retrieve a stored email by UID."""
        raise NotImplementedError

    def delete_email(self, uid: int) -> bool:
        """Remove an email and related records. Returns ``True`` if deleted."""
        raise NotImplementedError

    def get_checkpoint(self, mailbox: str) -> SyncCheckpoint | None:
        """Return the last stored checkpoint for the given mailbox."""
        raise NotImplementedError

    def upsert_checkpoint(self, checkpoint: SyncCheckpoint) -> None:
        """Persist the latest checkpoint for a mailbox."""
        raise NotImplementedError

    def persist_insight(self, insight: EmailInsight) -> None:
        """Store summarisation and prioritisation results for an email."""
        raise NotImplementedError

    def fetch_insight(self, email_uid: int) -> EmailInsight | None:
        """Retrieve stored insight for an email if available."""
        raise NotImplementedError

    def persist_draft(self, draft: DraftRecord) -> DraftRecord:
        """Save a generated draft reply and return the stored record."""
        raise NotImplementedError

    def list_recent_insights(
        self,
        limit: int,
        *,
        min_priority: int | None = None,
        max_priority: int | None = None,
        category_key: str | None = None,
        require_follow_up: bool = False,
    ) -> list[tuple[EmailEnvelope, EmailInsight]]:
        """Return recent emails joined with their insights for quick browsing."""
        raise NotImplementedError

    def count_insights(
        self,
        *,
        min_priority: int | None = None,
        max_priority: int | None = None,
        category_key: str | None = None,
        require_follow_up: bool = False,
    ) -> int:
        """Return total stored insights matching optional filters."""
        raise NotImplementedError

    def list_recent_drafts(self, limit: int) -> list[DraftRecord]:
        """Return recently generated drafts sorted by newest first."""
        raise NotImplementedError

    def fetch_latest_drafts(self, uids: Sequence[int]) -> dict[int, DraftRecord]:
        """Return the newest draft for each supplied email UID."""
        raise NotImplementedError

    def update_draft_body(
        self,
        draft_id: int,
        email_uid: int,
        *,
        body: str,
        provider: str,
        generated_at: datetime,
        confidence: float | None = None,
        used_fallback: bool = False,
    ) -> DraftRecord | None:
        """Update the stored draft contents and metadata."""
        raise NotImplementedError

    def delete_draft(self, draft_id: int, email_uid: int) -> bool:
        """Delete the stored draft for the given identifiers."""
        raise NotImplementedError

    def replace_categories(
        self, email_uid: int, categories: Sequence[EmailCategory]
    ) -> None:
        """Replace stored categories for an email."""
        raise NotImplementedError

    def get_categories_for_uids(
        self, uids: Sequence[int]
    ) -> dict[int, tuple[EmailCategory, ...]]:
        """Return categories for each requested email UID."""
        raise NotImplementedError

    def fetch_follow_ups_for_uids(
        self, uids: Sequence[int]
    ) -> dict[int, tuple[FollowUpTask, ...]]:
        """Return follow-up tasks grouped by email UID."""
        raise NotImplementedError

    def replace_follow_ups(self, email_uid: int, tasks: Sequence[FollowUpTask]) -> None:
        """Replace follow-up tasks for an email with the supplied tasks."""
        raise NotImplementedError

    def list_follow_ups(
        self, *, status: str | None = None, limit: int | None = None
    ) -> list[FollowUpTask]:
        """Return follow-up tasks optionally filtered by status."""
        raise NotImplementedError

    def list_categories(self) -> tuple[EmailCategory, ...]:
        """Return distinct categories currently stored in the repository."""
        raise NotImplementedError

    def update_follow_up_status(self, follow_up_id: int, status: str) -> None:
        """Set the status for a follow-up entry."""
        raise NotImplementedError

    def close(self) -> None:
        """Close database connections if necessary."""
        raise NotImplementedError


class InsightService(Protocol):
    """Provides summarisation and prioritisation for emails."""

    def generate_insight(self, email: EmailEnvelope) -> EmailInsight:
        """Produce an :class:`EmailInsight` for an email."""
        raise NotImplementedError


class DraftingService(Protocol):
    """Generates reply drafts for emails."""

    def generate_draft(
        self, email: EmailEnvelope, insight: EmailInsight
    ) -> DraftRecord:
        """Return a draft reply for the provided email."""
        raise NotImplementedError


class FollowUpPlanner(Protocol):
    """Derives follow-up tasks from email insights."""

    def plan_follow_ups(
        self, email: EmailEnvelope, insight: EmailInsight
    ) -> Sequence[FollowUpTask]:
        """Return follow-up tasks for the supplied email."""
        raise NotImplementedError


class CategoryService(Protocol):
    """Assigns categories/tags to emails based on content."""

    def categorize(
        self, email: EmailEnvelope, insight: EmailInsight | None
    ) -> Sequence[EmailCategory]:
        """Return ordered categories for the supplied email."""
        raise NotImplementedError


__all__ = [
    "EmailRepository",
    "MailboxProvider",
    "InsightError",
    "InsightService",
    "DraftingService",
    "FollowUpPlanner",
    "CategoryService",
]
