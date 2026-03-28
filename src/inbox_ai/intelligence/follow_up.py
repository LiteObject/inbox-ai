"""Plan follow-up tasks from email insights."""

from __future__ import annotations

import calendar
import logging
import re
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

        LOGGER.debug(
            "Planning follow-ups for UID %s with %d action items (priority=%s)",
            email.uid,
            len(insight.action_items),
            insight.priority,
        )

        for raw_item in insight.action_items:
            action = raw_item.strip()
            if not action:
                continue
            lowered = action.lower()
            if lowered in seen:
                LOGGER.debug(
                    "Skipped duplicate action for UID %s: %s", email.uid, action
                )
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
            LOGGER.debug(
                "No follow-up tasks derived for UID %s (no non-empty action items)",
                email.uid,
            )
        else:
            LOGGER.debug(
                "Created %d follow-up task(s) for UID %s", len(tasks), email.uid
            )

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
    duration_match = re.search(
        r"\bwithin\s+(\d+)\s+(hour|hours|day|days|week|weeks)\b",
        text,
    )
    if duration_match:
        amount = int(duration_match.group(1))
        unit = duration_match.group(2)
        if "hour" in unit:
            return baseline + timedelta(hours=amount)
        if "week" in unit:
            return baseline + timedelta(weeks=amount)
        return baseline + timedelta(days=amount)

    weekday_match = re.search(
        r"\b(?:by|before|on)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
        text,
    )
    if weekday_match:
        return _next_weekday(baseline, weekday_match.group(1))

    quarter_match = re.search(r"\bend of q([1-4])\b", text)
    if quarter_match:
        return _quarter_end(baseline, int(quarter_match.group(1)))

    if "end of month" in text:
        return _month_end(baseline)
    if "end of day" in text or re.search(r"\beod\b", text):
        return baseline.replace(hour=17, minute=0, second=0, microsecond=0)
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


def _next_weekday(baseline: datetime, weekday_name: str) -> datetime:
    weekday_index = list(calendar.day_name).index(weekday_name.capitalize())
    days_ahead = (weekday_index - baseline.weekday()) % 7
    candidate = baseline + timedelta(days=days_ahead)
    return candidate.replace(hour=17, minute=0, second=0, microsecond=0)


def _quarter_end(baseline: datetime, quarter: int) -> datetime:
    year = baseline.year
    month = quarter * 3
    last_day = calendar.monthrange(year, month)[1]
    candidate = baseline.replace(
        year=year,
        month=month,
        day=last_day,
        hour=17,
        minute=0,
        second=0,
        microsecond=0,
    )
    if candidate < baseline:
        year += 1
        last_day = calendar.monthrange(year, month)[1]
        candidate = candidate.replace(year=year, day=last_day)
    return candidate


def _month_end(baseline: datetime) -> datetime:
    last_day = calendar.monthrange(baseline.year, baseline.month)[1]
    candidate = baseline.replace(
        day=last_day,
        hour=17,
        minute=0,
        second=0,
        microsecond=0,
    )
    if candidate < baseline:
        next_month = baseline.month + 1
        next_year = baseline.year
        if next_month == 13:
            next_month = 1
            next_year += 1
        last_day = calendar.monthrange(next_year, next_month)[1]
        candidate = candidate.replace(year=next_year, month=next_month, day=last_day)
    return candidate


__all__ = ["FollowUpPlannerService"]
