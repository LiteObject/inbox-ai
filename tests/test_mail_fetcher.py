"""Tests for the mail fetch orchestration logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence

from inbox_ai.core.models import (
    DraftRecord,
    EmailBody,
    EmailEnvelope,
    EmailInsight,
    FollowUpTask,
    MessageChunk,
    SyncCheckpoint,
)
from inbox_ai.ingestion import MailFetcher


@dataclass
class RecordedEmail:
    uid: int
    subject: str | None


class DummyMailbox:
    """Mailbox provider returning predetermined chunks."""

    def __init__(self, mailbox: str, chunks: Iterable[MessageChunk]) -> None:
        self.mailbox = mailbox
        self._chunks = list(chunks)

    def fetch_since(
        self, last_uid: int | None, batch_size: int
    ) -> Iterable[MessageChunk]:
        assert batch_size == 2
        start_index = 0
        if last_uid is not None:
            for idx, chunk in enumerate(self._chunks):
                if chunk.uid > last_uid:
                    start_index = idx
                    break
        return self._chunks[start_index:]

    def close(self) -> None:
        return None


class RecordingRepository:
    """In-memory repository capturing persisted emails and checkpoints."""

    def __init__(self) -> None:
        self.persisted: List[RecordedEmail] = []
        self.checkpoint: SyncCheckpoint | None = None
        self.insights: list[int] = []
        self._insight_store: dict[int, EmailInsight] = {}
        self.drafts: list[int] = []
        self.follow_up_replacements: list[tuple[int, tuple[str, ...]]] = []
        self._emails: dict[int, EmailEnvelope] = {}

    def persist_email(self, email: EmailEnvelope) -> None:
        self.persisted.append(RecordedEmail(uid=email.uid, subject=email.subject))
        self._emails[email.uid] = email

    def fetch_email(self, uid: int) -> EmailEnvelope | None:
        return self._emails.get(uid)

    def persist_insight(self, insight: EmailInsight) -> None:
        self.insights.append(insight.email_uid)
        self._insight_store[insight.email_uid] = insight

    def fetch_insight(self, email_uid: int) -> EmailInsight | None:
        return self._insight_store.get(email_uid)

    def delete_email(self, uid: int) -> bool:
        self._emails.pop(uid, None)
        self._insight_store.pop(uid, None)
        return True

    def count_insights(self) -> int:
        return len(self._insight_store)

    def get_checkpoint(self, mailbox: str) -> SyncCheckpoint | None:
        return (
            self.checkpoint
            if self.checkpoint and self.checkpoint.mailbox == mailbox
            else None
        )

    def upsert_checkpoint(self, checkpoint: SyncCheckpoint) -> None:
        self.checkpoint = checkpoint

    def persist_draft(self, draft: DraftRecord) -> DraftRecord:
        self.drafts.append(draft.email_uid)
        return draft

    def replace_follow_ups(self, email_uid: int, tasks: Iterable[FollowUpTask]) -> None:
        actions = tuple(task.action for task in tasks)
        self.follow_up_replacements.append((email_uid, actions))

    def list_follow_ups(self, *, status: str | None = None, limit: int | None = None):
        del status, limit
        return []

    def list_recent_drafts(self, limit: int):
        del limit
        return []

    def list_recent_insights(
        self,
        limit: int,
        *,
        min_priority: int | None = None,
        max_priority: int | None = None,
    ):
        del limit, min_priority, max_priority
        return []

    def fetch_latest_drafts(self, uids: Sequence[int]):
        del uids
        return {}

    def update_follow_up_status(self, follow_up_id: int, status: str) -> None:
        del follow_up_id, status

    def close(self) -> None:
        return None


class StubParser:
    """Parser returning fixed envelopes without inspecting payload."""

    def parse(self, uid: int, payload: bytes) -> EmailEnvelope:
        body = EmailBody(text="stub", html=None)
        del payload
        return EmailEnvelope(
            uid=uid,
            message_id=f"<{uid}@example.com>",
            thread_id=None,
            subject=f"Message {uid}",
            sender="sender@example.com",
            to=("user@example.com",),
            cc=(),
            bcc=(),
            sent_at=None,
            received_at=None,
            body=body,
            attachments=(),
        )


class StubInsightService:
    """Deterministic insight generator for tests."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def generate_insight(self, email: EmailEnvelope) -> EmailInsight:
        self.calls.append(email.uid)
        return EmailInsight(
            email_uid=email.uid,
            summary=f"Summary {email.uid}",
            action_items=(f"Do {email.uid}",),
            priority=5,
            provider="test",
            generated_at=datetime.now(tz=timezone.utc),
            used_fallback=False,
        )


class StubDraftingService:
    """Drafting service returning canned drafts for testing."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def generate_draft(
        self, email: EmailEnvelope, insight: EmailInsight
    ) -> DraftRecord:
        self.calls.append(email.uid)
        del insight
        return DraftRecord(
            id=None,
            email_uid=email.uid,
            body=f"Draft {email.uid}",
            provider="stub",
            generated_at=datetime.now(tz=timezone.utc),
            confidence=0.9,
            used_fallback=False,
        )


class StubFollowUpPlanner:
    """Planner returning a single follow-up action for verification."""

    def __init__(self) -> None:
        self.calls: list[int] = []

    def plan_follow_ups(
        self, email: EmailEnvelope, insight: EmailInsight
    ) -> tuple[FollowUpTask, ...]:
        self.calls.append(email.uid)
        del insight
        task = FollowUpTask(
            id=None,
            email_uid=email.uid,
            action=f"Follow up {email.uid}",
            due_at=None,
            status="open",
            created_at=datetime.now(tz=timezone.utc),
            completed_at=None,
        )
        return (task,)


def test_mail_fetcher_persists_messages_and_updates_checkpoint() -> None:
    mailbox = DummyMailbox(
        mailbox="INBOX",
        chunks=[
            MessageChunk(uid=1, raw=b""),
            MessageChunk(uid=2, raw=b""),
        ],
    )
    repository = RecordingRepository()
    parser = StubParser()

    fetcher = MailFetcher(
        mailbox=mailbox,
        repository=repository,
        parser=parser,
        batch_size=2,
        max_messages=None,
    )

    result = fetcher.run()

    assert result.processed == 2
    assert result.new_last_uid == 2
    assert repository.checkpoint == SyncCheckpoint(mailbox="INBOX", last_uid=2)
    assert [email.subject for email in repository.persisted] == [
        "Message 1",
        "Message 2",
    ]


def test_mail_fetcher_honours_existing_checkpoint() -> None:
    mailbox = DummyMailbox(
        mailbox="INBOX",
        chunks=[
            MessageChunk(uid=3, raw=b""),
            MessageChunk(uid=4, raw=b""),
        ],
    )
    repository = RecordingRepository()
    repository.checkpoint = SyncCheckpoint(mailbox="INBOX", last_uid=3)
    parser = StubParser()

    fetcher = MailFetcher(
        mailbox=mailbox,
        repository=repository,
        parser=parser,
        batch_size=2,
        max_messages=1,
    )

    result = fetcher.run()

    assert result.processed == 1
    assert result.new_last_uid == 4
    assert repository.checkpoint == SyncCheckpoint(mailbox="INBOX", last_uid=4)


def test_mail_fetcher_generates_insights_when_service_provided() -> None:
    mailbox = DummyMailbox(
        mailbox="INBOX",
        chunks=[MessageChunk(uid=7, raw=b"")],
    )
    repository = RecordingRepository()
    parser = StubParser()
    insight_service = StubInsightService()

    fetcher = MailFetcher(
        mailbox=mailbox,
        repository=repository,
        parser=parser,
        batch_size=2,
        max_messages=None,
        insight_service=insight_service,
    )

    fetcher.run()

    assert insight_service.calls == [7]
    assert repository.insights == [7]


def test_mail_fetcher_generates_drafts_and_follow_ups() -> None:
    mailbox = DummyMailbox(
        mailbox="INBOX",
        chunks=[MessageChunk(uid=11, raw=b"")],
    )
    repository = RecordingRepository()
    parser = StubParser()
    insight_service = StubInsightService()
    drafting_service = StubDraftingService()
    follow_up_planner = StubFollowUpPlanner()

    fetcher = MailFetcher(
        mailbox=mailbox,
        repository=repository,
        parser=parser,
        batch_size=2,
        max_messages=None,
        insight_service=insight_service,
        drafting_service=drafting_service,
        follow_up_planner=follow_up_planner,
    )

    fetcher.run()

    assert drafting_service.calls == [11]
    assert repository.drafts == [11]
    assert follow_up_planner.calls == [11]
    assert repository.follow_up_replacements == [(11, ("Follow up 11",))]
