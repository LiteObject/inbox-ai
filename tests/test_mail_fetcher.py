"""Tests for the mail fetch orchestration logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, List, Sequence

from inbox_ai.core.models import (
    DraftRecord,
    EmailBody,
    EmailCategory,
    EmailEnvelope,
    EmailInsight,
    FollowUpTask,
    MessageChunk,
    SyncCheckpoint,
)
from inbox_ai.core.config import StorageSettings
from inbox_ai.ingestion import MailFetcher, OptimizedMailFetcher
from inbox_ai.intelligence import EmailAnalysis
from inbox_ai.intelligence.email_analysis_service import (
    FollowUpTask as AnalyzerFollowUpTask,
)
from inbox_ai.storage import SqliteEmailRepository


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

    def parse(self, uid: int, payload: bytes, mailbox: str) -> EmailEnvelope:
        body = EmailBody(text="stub", html=None)
        del payload
        return EmailEnvelope(
            uid=uid,
            mailbox=mailbox,
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


class StableContentParser(StubParser):
    """Parser that returns the same content across UIDs for cache tests."""

    def parse(self, uid: int, payload: bytes, mailbox: str) -> EmailEnvelope:
        envelope = super().parse(uid, payload, mailbox)
        return EmailEnvelope(
            uid=uid,
            mailbox=mailbox,
            message_id=envelope.message_id,
            thread_id=envelope.thread_id,
            subject="Cached message",
            sender=envelope.sender,
            to=envelope.to,
            cc=envelope.cc,
            bcc=envelope.bcc,
            sent_at=envelope.sent_at,
            received_at=envelope.received_at,
            body=EmailBody(text="cached body", html=None),
            attachments=envelope.attachments,
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


class StubOptimizedAnalyzer:
    """Composite analyzer stub returning prebuilt analysis results."""

    def __init__(self, analyses: list[EmailAnalysis]) -> None:
        self._analyses = analyses
        self.calls: list[list[int]] = []
        self._metrics = type(
            "Metrics",
            (),
            {
                "total_calls": 0,
                "total_tokens_input": 0,
                "total_tokens_output": 0,
                "cache_hits": 0,
                "cache_misses": 0,
                "get_summary": lambda self: {"total_calls": self.total_calls},
            },
        )()
        self.llm = type("LLM", (), {"provider_id": "stub-optimized"})()

    async def analyze_batch(
        self, envelopes: list[EmailEnvelope]
    ) -> list[EmailAnalysis]:
        self.calls.append([envelope.uid for envelope in envelopes])
        self._metrics.total_calls += len(envelopes)
        return self._analyses[: len(envelopes)]

    def get_metrics(self):
        return self._metrics


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


def test_optimized_mail_fetcher_persists_composite_outputs(tmp_path) -> None:
    mailbox = DummyMailbox(mailbox="INBOX", chunks=[MessageChunk(uid=21, raw=b"")])
    repository = SqliteEmailRepository(
        StorageSettings(db_path=tmp_path / "optimized.db")
    )
    parser = StubParser()
    analyzer = StubOptimizedAnalyzer(
        [
            EmailAnalysis(
                summary="Need support help soon.",
                priority=8,
                priority_label="High",
                action_items=["Reply to the customer"],
                categories=["support", "high_priority"],
                follow_ups=[
                    AnalyzerFollowUpTask(
                        action="Reply to the customer",
                        due_date="2026-03-28",
                    )
                ],
                suggested_reply="Thanks for reaching out. We are on it.",
            )
        ]
    )

    fetcher = OptimizedMailFetcher(
        mailbox=mailbox,
        repository=repository,
        parser=parser,
        analyzer=analyzer,
        batch_size=2,
        max_messages=None,
        analysis_batch_size=1,
        user_email="user@example.com",
    )

    result, _ = fetcher.run()

    assert result.processed == 1
    insight = repository.fetch_insight(21)
    assert insight is not None
    assert insight.summary == "Need support help soon."
    assert insight.priority == 8
    categories = repository.get_categories_for_uids([21])[21]
    assert categories == (
        EmailCategory(key="high_priority", label="High Priority"),
        EmailCategory(key="support", label="Support Request"),
    )
    drafts = repository.fetch_latest_drafts([21])
    assert drafts[21].body == "Thanks for reaching out. We are on it."
    follow_ups = repository.fetch_follow_ups_for_uids([21])[21]
    assert len(follow_ups) == 1
    assert follow_ups[0].action == "Reply to the customer"
    assert follow_ups[0].status == "open"
    repository.close()


def test_optimized_mail_fetcher_reuses_cached_outputs(tmp_path) -> None:
    repository = SqliteEmailRepository(StorageSettings(db_path=tmp_path / "cached.db"))
    seed_email = StableContentParser().parse(uid=30, payload=b"", mailbox="INBOX")
    repository.persist_email(seed_email)
    repository.update_content_hash(
        30, OptimizedMailFetcher._compute_content_hash(seed_email)
    )
    generated_at = datetime.now(tz=timezone.utc)
    repository.persist_insight(
        EmailInsight(
            email_uid=30,
            summary="Cached summary",
            action_items=("Cached action",),
            priority=6,
            provider="cached-provider",
            generated_at=generated_at,
            used_fallback=False,
        )
    )
    repository.replace_categories(
        30,
        (EmailCategory(key="support", label="Support Request"),),
    )
    repository.persist_draft(
        DraftRecord(
            id=None,
            email_uid=30,
            body="Cached draft",
            provider="cached-provider",
            generated_at=generated_at,
            confidence=0.9,
            used_fallback=False,
        )
    )
    repository.replace_follow_ups(
        30,
        (
            FollowUpTask(
                id=None,
                email_uid=30,
                action="Cached action",
                due_at=generated_at,
                status="open",
                created_at=generated_at,
                completed_at=None,
            ),
        ),
    )

    mailbox = DummyMailbox(mailbox="INBOX", chunks=[MessageChunk(uid=31, raw=b"")])
    parser = StableContentParser()
    analyzer = StubOptimizedAnalyzer([])
    fetcher = OptimizedMailFetcher(
        mailbox=mailbox,
        repository=repository,
        parser=parser,
        analyzer=analyzer,
        batch_size=2,
        max_messages=None,
        analysis_batch_size=1,
        user_email="user@example.com",
    )

    result, _ = fetcher.run()

    assert result.processed == 1
    assert analyzer.calls == []
    copied_insight = repository.fetch_insight(31)
    assert copied_insight is not None
    assert copied_insight.summary == "Cached summary"
    copied_categories = repository.get_categories_for_uids([31])[31]
    assert copied_categories == (EmailCategory(key="support", label="Support Request"),)
    copied_draft = repository.fetch_latest_drafts([31])[31]
    assert copied_draft.body == "Cached draft"
    copied_follow_ups = repository.fetch_follow_ups_for_uids([31])[31]
    assert copied_follow_ups[0].action == "Cached action"
    repository.close()
