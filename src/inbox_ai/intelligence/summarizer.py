"""Services that combine LLM output with deterministic fallbacks."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from inbox_ai.core.interfaces import InsightError, InsightService
from inbox_ai.core.models import EmailBody, EmailEnvelope, EmailInsight

from .fallback import build_deterministic_summary
from .llm import LLMClient, LLMError
from .priority import score_priority
from .prompts import build_insight_prompt

LOGGER = logging.getLogger(__name__)


class SummarizationService(InsightService):
    """Generate email insights using an LLM with a deterministic fallback."""

    def __init__(
        self,
        llm_client: LLMClient | None,
        *,
        fallback_enabled: bool = True,
        priority_fn: Callable[
            [EmailEnvelope, str, Sequence[str]], int
        ] = score_priority,
    ) -> None:
        """Prepare the insight generator with optional LLM and heuristics."""
        self._llm_client = llm_client
        self._fallback_enabled = fallback_enabled
        self._priority_fn = priority_fn

    def generate_insight(self, email: EmailEnvelope) -> EmailInsight:
        """Produce an insight record summarising ``email``."""
        try:
            body_text = _resolve_body_text(email.body)
            summary: str | None = None
            action_items: list[str] = []
            provider = "none"
            used_fallback = False

            if self._llm_client is not None:
                prompt = build_insight_prompt(email, body_text=body_text)
                try:
                    raw_output = self._llm_client.generate(prompt)
                    summary, action_items = _parse_llm_output(raw_output)
                    provider = self._llm_client.provider_id
                except (LLMError, ValueError) as exc:
                    LOGGER.warning(
                        "LLM summarisation failed for UID %s: %s", email.uid, exc
                    )
                    summary = None
                    action_items = []

            if (summary is None or not summary) and self._fallback_enabled:
                summary, action_items = build_deterministic_summary(
                    email, body_text=body_text
                )
                provider = "deterministic"
                used_fallback = True

            if summary is None or not summary:
                summary = "No summary available."

            cleaned_actions = [item.strip() for item in action_items if item.strip()]
            priority = self._priority_fn(email, summary, cleaned_actions)
            generated_at = datetime.now(tz=UTC)

            return EmailInsight(
                email_uid=email.uid,
                summary=summary,
                action_items=tuple(cleaned_actions),
                priority=priority,
                provider=provider,
                generated_at=generated_at,
                used_fallback=used_fallback,
            )
        except InsightError:
            raise
        except Exception as exc:  # noqa: BLE001 - defensive wrapping
            raise InsightError("Insight generation failed") from exc


def _resolve_body_text(body: EmailBody) -> str:
    if body.text:
        return body.text
    if body.html:
        return _strip_html(body.html)
    return ""


def _strip_html(payload: str) -> str:
    cleaned = []
    skip = False
    for char in payload:
        if char == "<":
            skip = True
            continue
        if char == ">":
            skip = False
            cleaned.append(" ")
            continue
        if not skip:
            cleaned.append(char)
    return "".join(cleaned)


def _parse_llm_output(raw: str) -> tuple[str, list[str]]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM output was not valid JSON") from exc

    summary = payload.get("summary")
    items = payload.get("action_items", [])

    if not isinstance(summary, str):
        raise ValueError("LLM output missing 'summary'")
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        raise ValueError("LLM output 'action_items' must be a list of strings")

    normalised_items = [item.strip() for item in items if item.strip()]
    return summary.strip(), normalised_items


__all__ = ["SummarizationService"]
