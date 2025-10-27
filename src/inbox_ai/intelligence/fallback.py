"""Deterministic heuristics used when the LLM is unavailable."""

from __future__ import annotations

import re
from collections.abc import Iterable

from inbox_ai.core.models import EmailEnvelope

_KEYWORD_PATTERNS = (
    re.compile(r"\burgent\b", re.IGNORECASE),
    re.compile(r"\basap\b", re.IGNORECASE),
    re.compile(r"\baction required\b", re.IGNORECASE),
    re.compile(r"\bplease\b", re.IGNORECASE),
)


def build_deterministic_summary(
    email: EmailEnvelope, *, body_text: str
) -> tuple[str, list[str]]:
    """Produce a lightweight summary and action list from plain text."""
    summary_segments = _collect_summary_segments(email, body_text)
    summary = " ".join(summary_segments).strip()
    if not summary:
        summary = "No summary available."

    action_items = [_normalise_line(line) for line in _collect_action_items(body_text)]
    filtered_actions = [item for item in action_items if item]
    return summary[:500], filtered_actions[:5]


def _collect_summary_segments(email: EmailEnvelope, body_text: str) -> list[str]:
    segments: list[str] = []
    if email.subject:
        segments.append(email.subject.strip())
    primary_text = body_text.strip().splitlines()
    for line in primary_text:
        cleaned = line.strip()
        if cleaned:
            segments.append(cleaned)
        if len(segments) >= 3:
            break
    return segments


def _collect_action_items(body_text: str) -> Iterable[str]:
    for line in body_text.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.lower().startswith(("please", "todo", "action", "kindly")):
            yield cleaned
            continue
        if any(pattern.search(cleaned) for pattern in _KEYWORD_PATTERNS):
            yield cleaned


def _normalise_line(line: str) -> str:
    line = line.strip()
    return re.sub(r"\s+", " ", line)


__all__ = ["build_deterministic_summary"]
