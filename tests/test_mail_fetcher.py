"""Tests for the mail fetch orchestration logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from inbox_ai.core.models import EmailBody, EmailEnvelope, MessageChunk, SyncCheckpoint
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

    def persist_email(self, email: EmailEnvelope) -> None:
        self.persisted.append(RecordedEmail(uid=email.uid, subject=email.subject))

    def get_checkpoint(self, mailbox: str) -> SyncCheckpoint | None:
        return (
            self.checkpoint
            if self.checkpoint and self.checkpoint.mailbox == mailbox
            else None
        )

    def upsert_checkpoint(self, checkpoint: SyncCheckpoint) -> None:
        self.checkpoint = checkpoint

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
