"""Drafting service that produces reply templates for emails."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from inbox_ai.core.interfaces import DraftingService as DraftingServiceProtocol
from inbox_ai.core.models import DraftRecord, EmailEnvelope, EmailInsight

from .llm import LLMClient, LLMError
from .prompts import build_draft_prompt

LOGGER = logging.getLogger(__name__)


class DraftingError(RuntimeError):
    """Raised when drafting fails and no fallback can be produced."""


class DraftingService(DraftingServiceProtocol):
    """Generate reply drafts using an LLM with deterministic fallback."""

    def __init__(
        self,
        llm_client: LLMClient | None,
        *,
        fallback_enabled: bool = True,
    ) -> None:
        """Initialise the service with an optional LLM client and fallback flag."""
        self._llm_client = llm_client
        self._fallback_enabled = fallback_enabled

    def generate_draft(
        self, email: EmailEnvelope, insight: EmailInsight
    ) -> DraftRecord:
        """Return a draft reply body for ``email``."""
        body: str | None = None
        confidence: float | None = None
        provider = "none"
        used_fallback = False

        if self._llm_client is not None:
            prompt = build_draft_prompt(email, insight)
            try:
                raw_output = self._llm_client.generate(prompt)
                body, confidence = _parse_draft_output(raw_output)
                provider = self._llm_client.provider_id
            except (LLMError, ValueError) as exc:
                LOGGER.warning("LLM drafting failed for UID %s: %s", email.uid, exc)
                body = None
                confidence = None

        if (body is None or not body.strip()) and self._fallback_enabled:
            body = _fallback_reply(email, insight)
            confidence = 0.25
            provider = "deterministic"
            used_fallback = True

        if body is None or not body.strip():
            raise DraftingError("Draft reply could not be generated")

        generated_at = datetime.now(tz=UTC)
        return DraftRecord(
            id=None,
            email_uid=email.uid,
            body=body.strip(),
            provider=provider,
            generated_at=generated_at,
            confidence=confidence,
            used_fallback=used_fallback,
        )


def _parse_draft_output(raw: str) -> tuple[str, float | None]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Draft output was not valid JSON") from exc

    draft = payload.get("draft")
    if not isinstance(draft, str):
        raise ValueError("Draft output missing 'draft' field")

    confidence_value = payload.get("confidence")
    confidence: float | None = None
    if confidence_value is not None:
        if isinstance(confidence_value, (int, float)):
            confidence = float(confidence_value)
        else:
            raise ValueError("Draft output 'confidence' must be numeric")

    return draft.strip(), confidence


def _fallback_reply(email: EmailEnvelope, insight: EmailInsight) -> str:
    name_hint = email.sender.split("@")[0] if email.sender else "there"
    greeting = f"Hi {name_hint},"
    subject = email.subject or "your message"
    summary = insight.summary
    closing = "Best regards,\n<Your Name>"
    lines = [
        greeting,
        "",
        f"Thanks for reaching out about {subject}.",
        summary,
    ]
    if insight.action_items:
        lines.append("")
        lines.append("Next steps:")
        for item in insight.action_items[:3]:
            lines.append(f"- {item}")
    lines.extend(["", closing])
    return "\n".join(lines)


__all__ = ["DraftingService", "DraftingError"]
