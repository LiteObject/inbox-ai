"""Prompt templates for LLM-driven summaries."""

from __future__ import annotations

from textwrap import dedent

from inbox_ai.core.models import EmailEnvelope, EmailInsight


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


def build_draft_prompt(email: EmailEnvelope, insight: EmailInsight) -> str:
    """Compose a prompt instructing the LLM to draft a reply."""
    subject = email.subject or "this message"
    sender = email.sender or "the sender"
    summary = insight.summary
    actions = "\n".join(f"- {item}" for item in insight.action_items) or "- none"

    prompt = f"""
    You assist with professional email replies. Return ONLY JSON matching this schema:
    {{
      "draft": string,            # the email body, with greeting and closing
      "confidence": number|null   # optional confidence between 0 and 1
    }}

    Base the reply on the following context.
    Subject: {subject}
    Sender: {sender}
    Summary: {summary}
    Action items:
    {actions}

    Draft should be concise, polite, and mention next steps when appropriate.
    """

    return dedent(prompt).strip()


__all__ = ["build_insight_prompt", "build_draft_prompt"]
