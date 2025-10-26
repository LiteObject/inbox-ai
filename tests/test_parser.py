"""Tests for RFC822 parsing into email envelopes."""

from __future__ import annotations

from pathlib import Path

from inbox_ai.ingestion import EmailParser

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sample_email.eml"


def test_email_parser_extracts_headers_and_bodies() -> None:
    payload = FIXTURE_PATH.read_bytes()
    parser = EmailParser()

    envelope = parser.parse(uid=101, payload=payload)

    assert envelope.uid == 101
    assert envelope.subject == "Test Email"
    assert envelope.sender == "sender@example.com"
    assert envelope.to == ("user@example.com",)
    assert envelope.cc == ("another@example.com",)
    assert envelope.bcc == ()
    assert envelope.message_id == "<1234@example.com>"
    assert envelope.thread_id == "<thread@example.com>"
    assert envelope.body.text == "Hello world."
    assert "<strong>world</strong>" in (envelope.body.html or "")
    assert len(envelope.attachments) == 1
    attachment = envelope.attachments[0]
    assert attachment.filename == "note.txt"
    assert attachment.content_type == "application/octet-stream"
    assert attachment.size == 18
