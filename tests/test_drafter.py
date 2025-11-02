"""Tests for the drafting service implementation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from inbox_ai.core.models import EmailBody, EmailEnvelope, EmailInsight
from inbox_ai.intelligence.drafter import DraftingError, DraftingService
from inbox_ai.intelligence.llm import LLMError


class StubLLM:
    """LLM stub returning a predetermined response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.provider_id = "stub-llm"
        self.last_prompt: str | None = None

    def generate(self, prompt: str) -> str:
        self.last_prompt = prompt
        return self.response


class FailingLLM:
    """LLM stub that always raises an error."""

    provider_id = "failing-llm"

    def generate(self, prompt: str) -> str:
        del prompt
        raise LLMError("failure")


def _sample_email() -> EmailEnvelope:
    return EmailEnvelope(
        uid=101,
        mailbox="INBOX",
        message_id="<101@example.com>",
        thread_id=None,
        subject="Project update",
        sender="alice@example.com",
        to=("team@example.com",),
        cc=(),
        bcc=(),
        sent_at=None,
        received_at=None,
        body=EmailBody(text="Body", html=None),
        attachments=(),
    )


def _sample_insight() -> EmailInsight:
    return EmailInsight(
        email_uid=101,
        summary="We should review the latest numbers and respond by Friday.",
        action_items=("Send the revised projections", "Confirm timeline"),
        priority=6,
        provider="stub",
        generated_at=datetime.now(tz=timezone.utc),
        used_fallback=False,
    )


def test_generate_draft_uses_llm_output() -> None:
    llm = StubLLM('{"draft": "Thanks!", "confidence": 0.8}')
    service = DraftingService(llm)

    draft = service.generate_draft(_sample_email(), _sample_insight())

    assert draft.body == "Thanks!"
    assert draft.provider == "stub-llm"
    assert draft.confidence == 0.8
    assert not draft.used_fallback
    assert draft.generated_at.tzinfo is not None


def test_generate_draft_falls_back_when_llm_fails() -> None:
    service = DraftingService(FailingLLM())

    draft = service.generate_draft(_sample_email(), _sample_insight())

    assert draft.provider == "deterministic"
    assert draft.used_fallback
    assert draft.confidence == 0.25
    assert "Next steps" in draft.body


def test_generate_draft_raises_when_no_fallback() -> None:
    service = DraftingService(FailingLLM(), fallback_enabled=False)

    with pytest.raises(DraftingError):
        service.generate_draft(_sample_email(), _sample_insight())
