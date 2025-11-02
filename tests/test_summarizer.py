"""Tests for the summarisation service."""

from __future__ import annotations

from datetime import datetime, timezone

from inbox_ai.core.models import EmailBody, EmailEnvelope
from inbox_ai.intelligence.summarizer import SummarizationService
from inbox_ai.intelligence.llm import LLMError


class StubLLM:
    """Stub LLM client returning predefined payloads."""

    def __init__(self, response: str | None, *, raise_error: bool = False) -> None:
        self.response = response
        self.raise_error = raise_error
        self.calls = 0

    @property
    def provider_id(self) -> str:
        return "stub-model"

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.raise_error:
            raise LLMError("stub failure")
        assert "summary" in prompt
        assert "Email body" in prompt
        assert self.response is not None
        return self.response


def _envelope() -> EmailEnvelope:
    return EmailEnvelope(
        uid=1,
        mailbox="INBOX",
        message_id="<1@example.com>",
        thread_id=None,
        subject="Quarterly update",
        sender="ceo@example.com",
        to=("user@example.com",),
        cc=(),
        bcc=(),
        sent_at=datetime.now(tz=timezone.utc),
        received_at=datetime.now(tz=timezone.utc),
        body=EmailBody(
            text="Please review the attached plan and reply ASAP.", html=None
        ),
        attachments=(),
    )


def test_summarizer_uses_llm_response() -> None:
    llm_response = (
        '{"summary": "Important update", "action_items": ["Reply with feedback"]}'
    )
    service = SummarizationService(StubLLM(llm_response))

    insight = service.generate_insight(_envelope())

    assert insight.summary == "Important update"
    assert insight.action_items == ("Reply with feedback",)
    assert insight.provider == "stub-model"
    assert not insight.used_fallback


def test_summarizer_fallback_on_llm_error() -> None:
    service = SummarizationService(StubLLM(None, raise_error=True))

    insight = service.generate_insight(_envelope())

    assert insight.summary != ""
    assert insight.provider == "deterministic"
    assert insight.used_fallback
    assert insight.priority >= 0
