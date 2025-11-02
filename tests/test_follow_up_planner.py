"""Tests for the follow-up planner service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from inbox_ai.core.config import FollowUpSettings
from inbox_ai.core.models import EmailBody, EmailEnvelope, EmailInsight
from inbox_ai.intelligence.follow_up import FollowUpPlannerService


def _email() -> EmailEnvelope:
    return EmailEnvelope(
        uid=202,
        mailbox="INBOX",
        message_id="<202@example.com>",
        thread_id=None,
        subject="Quarterly planning",
        sender="bob@example.com",
        to=("ops@example.com",),
        cc=(),
        bcc=(),
        sent_at=None,
        received_at=None,
        body=EmailBody(text="Details", html=None),
        attachments=(),
    )


def _insight(priority: int, generated_at: datetime, *items: str) -> EmailInsight:
    return EmailInsight(
        email_uid=202,
        summary="Summary",
        action_items=tuple(items),
        priority=priority,
        provider="stub",
        generated_at=generated_at,
        used_fallback=False,
    )


def test_planner_deduplicates_and_trims_actions() -> None:
    planner = FollowUpPlannerService(FollowUpSettings())
    generated_at = datetime(2025, 10, 26, 12, 0, tzinfo=timezone.utc)
    insight = _insight(
        5,
        generated_at,
        " Send proposal ",
        "",
        "send proposal",
        "Confirm schedule",
    )

    tasks = planner.plan_follow_ups(_email(), insight)

    assert len(tasks) == 2
    assert {task.action for task in tasks} == {"Send proposal", "Confirm schedule"}
    for task in tasks:
        assert task.status == "open"
        assert task.created_at >= generated_at


def test_planner_uses_priority_due_days() -> None:
    settings = FollowUpSettings(
        default_due_days=3, priority_due_days=1, priority_threshold=7
    )
    planner = FollowUpPlannerService(settings)
    generated_at = datetime(2025, 10, 26, 12, 0, tzinfo=timezone.utc)
    insight = _insight(8, generated_at, "Review financials")

    (task,) = planner.plan_follow_ups(_email(), insight)

    assert task.due_at == generated_at + timedelta(days=1)


def test_planner_detects_relative_keywords() -> None:
    planner = FollowUpPlannerService(FollowUpSettings())
    generated_at = datetime(2025, 10, 26, 14, 0, tzinfo=timezone.utc)
    insight = _insight(5, generated_at, "Call the client tomorrow")

    (task,) = planner.plan_follow_ups(_email(), insight)

    assert task.due_at == generated_at + timedelta(days=1)
