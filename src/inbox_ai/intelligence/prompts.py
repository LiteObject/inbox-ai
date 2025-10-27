"""Prompt templates for LLM-driven summaries."""

from __future__ import annotations

from textwrap import dedent

from inbox_ai.core.models import EmailEnvelope


def build_insight_prompt(email: EmailEnvelope, *, body_text: str) -> str:
    """Compose a JSON-only summarisation prompt for the email body."""
    to_line = ", ".join(email.to) if email.to else "(none)"
    cc_line = ", ".join(email.cc) if email.cc else "(none)"
    subject = email.subject or "(no subject)"
    sender = email.sender or "(unknown sender)"

    prompt = f"""
    You are an assistant that produces concise email digests.
    Respond strictly with JSON using this schema:
    {{
      "summary": string,  # 2-3 sentences describing the email
      "action_items": [string, ...]  # zero or more actionable bullet points
    }}

    Do not include any additional keys or prose outside the JSON object.

    Subject: {subject}
    From: {sender}
    To: {to_line}
    Cc: {cc_line}

    Email body:
    {body_text}
    """

    return dedent(prompt).strip()


__all__ = ["build_insight_prompt"]
