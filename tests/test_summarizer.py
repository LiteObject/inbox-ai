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
        self.last_prompt: str | None = None

    @property
    def provider_id(self) -> str:
        return "stub-model"

    def generate(
        self,
        prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        del temperature, max_tokens
        self.calls += 1
        self.last_prompt = prompt
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
    llm_response = '{"summary": "Important update", "action_items": ["Reply with feedback"], "priority": 8}'
    service = SummarizationService(
        StubLLM(llm_response),
        user_preferences="Flag security alerts as urgent.",
    )

    insight = service.generate_insight(_envelope())

    assert insight.summary == "Important update"
    assert insight.action_items == ("Reply with feedback",)
    assert insight.priority == 8
    assert insight.provider == "stub-model"
    assert not insight.used_fallback


def test_summarizer_includes_user_preferences_in_prompt() -> None:
    llm = StubLLM('{"summary": "Important update", "action_items": []}')
    service = SummarizationService(
        llm,
        user_preferences="Ignore newsletters. Treat customer escalations as urgent.",
    )

    service.generate_insight(_envelope())

    assert llm.last_prompt is not None
    assert "User context:" in llm.last_prompt
    assert (
        "Ignore newsletters. Treat customer escalations as urgent." in llm.last_prompt
    )


def test_summarizer_falls_back_to_heuristic_priority_when_llm_omits_priority() -> None:
    service = SummarizationService(
        StubLLM('{"summary": "Please reply ASAP.", "action_items": ["Reply today"]}')
    )

    insight = service.generate_insight(_envelope())

    assert insight.priority > 0


def test_summarizer_converts_html_to_structured_text() -> None:
    llm = StubLLM('{"summary": "HTML parsed", "action_items": []}')
    service = SummarizationService(llm)
    email = EmailEnvelope(
        uid=2,
        mailbox="INBOX",
        message_id="<2@example.com>",
        thread_id=None,
        subject="HTML message",
        sender="sender@example.com",
        to=("user@example.com",),
        cc=(),
        bcc=(),
        sent_at=datetime.now(tz=timezone.utc),
        received_at=datetime.now(tz=timezone.utc),
        body=EmailBody(
            text=None,
            html=(
                "<h1>Release notes</h1><p>Please review the items below.</p>"
                "<ul><li>Confirm rollout</li><li>Share update</li></ul>"
                '<p>Open the <a href="https://example.com/portal">portal</a>.</p>'
            ),
        ),
        attachments=(),
    )

    service.generate_insight(email)

    assert llm.last_prompt is not None
    assert "Release notes" in llm.last_prompt
    assert "- Confirm rollout" in llm.last_prompt
    assert "- Share update" in llm.last_prompt
    assert "portal (https://example.com/portal)" in llm.last_prompt


def test_summarizer_fallback_on_llm_error() -> None:
    service = SummarizationService(StubLLM(None, raise_error=True))

    insight = service.generate_insight(_envelope())

    assert insight.summary != ""
    assert insight.provider == "deterministic"
    assert insight.used_fallback
    assert insight.priority >= 0
