"""Prompt templates for LLM-driven summaries."""

from __future__ import annotations

from inbox_ai.core.models import EmailEnvelope, EmailInsight


def build_insight_prompt(
    email: EmailEnvelope, *, body_text: str, user_preferences: str = ""
) -> str:
    """Compose a JSON-only summarisation prompt for the email body."""
    to_line = ", ".join(email.to) if email.to else "(none)"
    cc_line = ", ".join(email.cc) if email.cc else "(none)"
    subject = email.subject or "(no subject)"
    sender = email.sender or "(unknown sender)"
    stripped_preferences = user_preferences.strip()

    prompt_lines = [
        "You are an assistant that produces concise email digests.",
        "Respond strictly with JSON using this schema:",
        "{",
        '  "summary": string,  # 2-3 sentences describing the email',
        '  "action_items": [string, ...],  # zero or more actionable bullet points',
        '  "priority": integer|null  # optional priority from 0 (low) to 10 (urgent)',
        "}",
        "",
        "Priority scale:",
        "- 0-2: Low priority, informational only",
        "- 3-5: Normal priority, respond in routine flow",
        "- 6-8: High priority, important or time-sensitive",
        "- 9-10: Urgent priority, immediate attention required",
        "",
        "Do not include any additional keys or prose outside the JSON object.",
        "",
        f"Subject: {subject}",
        f"From: {sender}",
        f"To: {to_line}",
        f"Cc: {cc_line}",
        "",
    ]
    if stripped_preferences:
        prompt_lines.extend(["User context:", stripped_preferences, ""])
    prompt_lines.extend(["Email body:", body_text])
    return "\n".join(prompt_lines)


def build_draft_prompt(
    email: EmailEnvelope,
    insight: EmailInsight,
    *,
    user_preferences: str = "",
    reply_tone: str = "Professional",
) -> str:
    """Compose a prompt instructing the LLM to draft a reply."""
    subject = email.subject or "this message"
    sender = email.sender or "the sender"
    summary = insight.summary
    actions = "\n".join(f"- {item}" for item in insight.action_items) or "- none"
    stripped_preferences = user_preferences.strip()

    prompt_lines = [
        "You assist with professional email replies. Return ONLY JSON matching this schema:",
        "{",
        '  "draft": string,            # the email body, with greeting and closing',
        '  "confidence": number|null   # optional confidence between 0 and 1',
        "}",
        "",
        "Base the reply on the following context.",
    ]
    if stripped_preferences:
        prompt_lines.extend(["User context:", stripped_preferences, ""])
    prompt_lines.extend(
        [
            f"Subject: {subject}",
            f"Sender: {sender}",
            f"Tone: {reply_tone}",
            f"Summary: {summary}",
            "Action items:",
            actions,
            "",
            "Draft should reflect the requested tone, stay professional, and mention next steps when appropriate.",
        ]
    )
    return "\n".join(prompt_lines)


__all__ = ["build_insight_prompt", "build_draft_prompt"]
