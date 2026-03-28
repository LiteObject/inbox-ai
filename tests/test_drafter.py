"""Tests for the drafting service implementation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from inbox_ai.core.models import EmailBody, EmailEnvelope, EmailInsight, ThreadSummary
from inbox_ai.intelligence.drafter import DraftingError, DraftingService
from inbox_ai.intelligence.llm import LLMError


class StubLLM:
    """LLM stub returning a predetermined response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.provider_id = "stub-llm"
        self.last_prompt: str | None = None

    def generate(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        del temperature, max_tokens
        self.last_prompt = prompt
        return self.response


class FailingLLM:
    """LLM stub that always raises an error."""

    provider_id = "failing-llm"

    def generate(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        del prompt, temperature, max_tokens
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
    service = DraftingService(
        llm,
        user_preferences="Keep replies brief and mention deadlines.",
        reply_tone="Detailed",
    )

    draft = service.generate_draft(_sample_email(), _sample_insight())

    assert draft.body == "Thanks!"
    assert draft.provider == "stub-llm"
    assert draft.confidence == 0.8
    assert not draft.used_fallback
    assert draft.generated_at.tzinfo is not None
    assert llm.last_prompt is not None
    assert "User context:" in llm.last_prompt
    assert "Keep replies brief and mention deadlines." in llm.last_prompt
    assert "Tone: Detailed" in llm.last_prompt


def test_generate_draft_includes_thread_context_in_prompt() -> None:
    llm = StubLLM('{"draft": "Thanks!", "confidence": 0.8}')
    service = DraftingService(
        llm,
        thread_context_provider=lambda thread_id, uid: (
            ThreadSummary(
                email_uid=uid - 1,
                subject="Prior exchange",
                sender="alice@example.com",
                summary="The sender already shared the requested numbers.",
            ),
        ),
    )
    email = _sample_email()
    email.thread_id = "thread-456"

    service.generate_draft(email, _sample_insight())

    assert llm.last_prompt is not None
    assert "Thread context:" in llm.last_prompt
    assert "maintain continuity" in llm.last_prompt.lower()
    assert "The sender already shared the requested numbers." in llm.last_prompt


def test_generate_draft_omits_user_context_when_preferences_empty() -> None:
    llm = StubLLM('{"draft": "Thanks!", "confidence": 0.8}')
    service = DraftingService(llm)

    service.generate_draft(_sample_email(), _sample_insight())

    assert llm.last_prompt is not None
    assert "User context:" not in llm.last_prompt


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
