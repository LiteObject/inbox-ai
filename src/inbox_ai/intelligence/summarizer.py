"""Services that combine LLM output with deterministic fallbacks."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from datetime import UTC, datetime

from inbox_ai.core.interfaces import InsightError, InsightService
from inbox_ai.core.models import EmailBody, EmailEnvelope, EmailInsight, EmailCategory

from .fallback import build_deterministic_summary
from .llm import LLMClient, LLMError
from .priority import score_priority
from .prompts import build_insight_prompt
from .text import body_to_text

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
        exclude_categories: Sequence[str] | None = None,
        user_preferences: str = "",
    ) -> None:
        """Prepare the insight generator with optional LLM and heuristics."""
        self._llm_client = llm_client
        self._fallback_enabled = fallback_enabled
        self._priority_fn = priority_fn
        self._exclude_categories = set(exclude_categories or [])
        self._user_preferences = user_preferences

    def generate_insight(
        self, email: EmailEnvelope, categories: Sequence[EmailCategory] | None = None
    ) -> EmailInsight:
        """Produce an insight record summarising ``email``."""
        try:
            body_text = _resolve_body_text(email.body)
            summary: str | None = None
            action_items: list[str] = []
            llm_priority: int | None = None
            provider = "none"
            used_fallback = False

            # Check if email should be excluded based on category
            is_excluded = False
            if categories is not None and self._exclude_categories:
                is_excluded = any(
                    cat.key in self._exclude_categories for cat in categories
                )

            if self._llm_client is not None:
                prompt = build_insight_prompt(
                    email,
                    body_text=body_text,
                    user_preferences=self._user_preferences,
                )
                try:
                    raw_output = self._llm_client.generate(prompt)
                    summary, action_items, llm_priority = _parse_llm_output(raw_output)
                    provider = self._llm_client.provider_id
                except (LLMError, ValueError) as exc:
                    LOGGER.warning(
                        "LLM summarisation failed for UID %s: %s", email.uid, exc
                    )
                    summary = None
                    action_items = []
                    llm_priority = None

            if (summary is None or not summary) and self._fallback_enabled:
                summary, action_items = build_deterministic_summary(
                    email, body_text=body_text
                )
                provider = "deterministic"
                used_fallback = True

            if summary is None or not summary:
                summary = "No summary available."

            # Filter out actions for excluded categories ONLY
            if is_excluded:
                LOGGER.debug(
                    "Filtered out %d action items for excluded category email UID %s",
                    len(action_items),
                    email.uid,
                )
                action_items = []

            cleaned_actions = [item.strip() for item in action_items if item.strip()]
            priority = (
                llm_priority
                if llm_priority is not None
                else self._priority_fn(email, summary, cleaned_actions)
            )
            generated_at = datetime.now(tz=UTC)

            LOGGER.debug(
                "Generated insight for UID %s: summary_len=%s, action_items=%d, priority=%s, provider=%s, used_fallback=%s",
                email.uid,
                len(summary) if summary else 0,
                len(cleaned_actions),
                priority,
                provider,
                used_fallback,
            )

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
    return body_to_text(body)


def _parse_llm_output(raw: str) -> tuple[str, list[str], int | None]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("LLM output was not valid JSON") from exc

    summary = payload.get("summary")
    items = payload.get("action_items", [])
    priority_value = payload.get("priority")

    if not isinstance(summary, str):
        raise ValueError("LLM output missing 'summary'")
    if not isinstance(items, list) or any(not isinstance(item, str) for item in items):
        raise ValueError("LLM output 'action_items' must be a list of strings")

    priority: int | None = None
    if priority_value is not None:
        if isinstance(priority_value, bool) or not isinstance(priority_value, int):
            raise ValueError("LLM output 'priority' must be an integer")
        if not 0 <= priority_value <= 10:
            raise ValueError("LLM output 'priority' must be between 0 and 10")
        priority = priority_value

    normalised_items = [item.strip() for item in items if item.strip()]
    return summary.strip(), normalised_items, priority


__all__ = ["SummarizationService"]
