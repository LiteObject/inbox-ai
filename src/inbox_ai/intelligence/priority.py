"""Heuristic priority scoring for emails."""

from __future__ import annotations

from collections.abc import Sequence

from inbox_ai.core.models import EmailEnvelope

_KEYWORD_WEIGHTS = {
    "urgent": 4,
    "asap": 3,
    "important": 2,
    "overdue": 2,
    "follow up": 1,
}
_SENDER_HINTS = {
    "ceo": 4,
    "founder": 3,
    "manager": 2,
}


def score_priority(
    email: EmailEnvelope,
    summary: str,
    action_items: Sequence[str],
) -> int:
    """Return a coarse priority score from 0 (low) to 10 (high)."""
    score = 0
    subject = (email.subject or "").lower()
    text = summary.lower()

    for keyword, weight in _KEYWORD_WEIGHTS.items():
        if keyword in subject or keyword in text:
            score += weight

    sender = (email.sender or "").lower()
    for hint, weight in _SENDER_HINTS.items():
        if hint in sender:
            score += weight
            break

    score += min(len(action_items), 3)

    if email.attachments:
        score += 1

    return max(0, min(score, 10))


__all__ = ["score_priority"]
