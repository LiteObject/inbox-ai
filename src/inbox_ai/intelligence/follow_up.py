"""Plan follow-up tasks from email insights."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from inbox_ai.core.config import FollowUpSettings
from inbox_ai.core.interfaces import FollowUpPlanner as FollowUpPlannerProtocol
from inbox_ai.core.models import EmailEnvelope, EmailInsight, FollowUpTask

LOGGER = logging.getLogger(__name__)


class FollowUpPlannerService(FollowUpPlannerProtocol):
    """Derive actionable follow-up tasks from insight action items."""

    def __init__(self, settings: FollowUpSettings) -> None:
        """Store scheduling heuristics drawn from application settings."""
        self._settings = settings

    def plan_follow_ups(
        self, email: EmailEnvelope, insight: EmailInsight
    ) -> tuple[FollowUpTask, ...]:
        """Generate unique follow-up tasks for an email based on insight data."""
        now = datetime.now(tz=UTC)
        tasks: list[FollowUpTask] = []
        seen: set[str] = set()
        for raw_item in insight.action_items:
            action = raw_item.strip()
            if not action:
                continue
            lowered = action.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            due_at = _estimate_due_at(
                action,
                insight_priority=insight.priority,
                generated_at=insight.generated_at,
                settings=self._settings,
            )
            tasks.append(
                FollowUpTask(
                    id=None,
                    email_uid=email.uid,
                    action=action,
                    due_at=due_at,
                    status="open",
                    created_at=now,
                    completed_at=None,
                )
            )
        if not tasks:
            LOGGER.debug("No follow-up tasks derived for UID %s", email.uid)
        return tuple(tasks)


def _estimate_due_at(
    action: str,
    *,
    insight_priority: int,
    generated_at: datetime,
    settings: FollowUpSettings,
) -> datetime | None:
    baseline = generated_at
    text = action.lower()
    if "today" in text:
        return baseline
    if "tomorrow" in text:
        return baseline + timedelta(days=1)
    if "next week" in text:
        return baseline + timedelta(days=7)
    if "next month" in text:
        return baseline + timedelta(days=30)

    days = settings.default_due_days
    if insight_priority >= settings.priority_threshold:
        days = settings.priority_due_days
    if days == 0:
        return baseline
    return baseline + timedelta(days=days)


__all__ = ["FollowUpPlannerService"]
