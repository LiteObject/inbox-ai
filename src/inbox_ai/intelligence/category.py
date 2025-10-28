"""Rule-based categorisation service for emails."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from inbox_ai.core.interfaces import CategoryService
from inbox_ai.core.models import EmailCategory, EmailEnvelope, EmailInsight

CategoryPredicate = Callable[[EmailEnvelope, EmailInsight | None, str], bool]


@dataclass(frozen=True)
class _CategoryRule:
    key: str
    label: str
    keywords: tuple[str, ...] = ()
    predicate: CategoryPredicate | None = None


class KeywordCategoryService(CategoryService):
    """Assign categories based on simple keyword heuristics."""

    def __init__(
        self,
        rules: Sequence[_CategoryRule] | None = None,
        *,
        default_category: EmailCategory | None = EmailCategory(
            key="general", label="General"
        ),
        max_categories: int | None = 3,
    ) -> None:
        self._rules: tuple[_CategoryRule, ...] = (
            tuple(rules)
            if rules is not None
            else (
                _CategoryRule(
                    key="high_priority",
                    label="High Priority",
                    predicate=lambda _email, insight, _text: bool(insight)
                    and insight.priority >= 8,
                ),
                _CategoryRule(
                    key="meeting",
                    label="Meetings",
                    keywords=(
                        "meeting",
                        "calendar",
                        "schedule",
                        "invite",
                        "call",
                        "zoom",
                        "webex",
                        "sync",
                    ),
                ),
                _CategoryRule(
                    key="billing",
                    label="Billing & Payments",
                    keywords=(
                        "invoice",
                        "payment",
                        "receipt",
                        "bill",
                        "billing",
                        "charge",
                        "refund",
                        "subscription",
                    ),
                ),
                _CategoryRule(
                    key="follow_up",
                    label="Follow Up",
                    keywords=(
                        "follow up",
                        "follow-up",
                        "check in",
                        "checking in",
                        "reminder",
                        "ping",
                    ),
                ),
                _CategoryRule(
                    key="sales",
                    label="Sales & Deals",
                    keywords=(
                        "proposal",
                        "quote",
                        "pricing",
                        "contract",
                        "renewal",
                        "deal",
                        "discount",
                    ),
                ),
                _CategoryRule(
                    key="support",
                    label="Support Request",
                    keywords=(
                        "support",
                        "issue",
                        "bug",
                        "error",
                        "trouble",
                        "incident",
                        "ticket",
                    ),
                ),
                _CategoryRule(
                    key="travel",
                    label="Travel",
                    keywords=(
                        "flight",
                        "hotel",
                        "booking",
                        "reservation",
                        "itinerary",
                        "travel",
                        "boarding",
                        "airline",
                    ),
                ),
                _CategoryRule(
                    key="recruiting",
                    label="Hiring & People",
                    keywords=(
                        "candidate",
                        "interview",
                        "resume",
                        "cv",
                        "onboarding",
                        "offer",
                        "payroll",
                    ),
                ),
                _CategoryRule(
                    key="attachments",
                    label="Has Attachments",
                    predicate=lambda email, _insight, _text: bool(email.attachments),
                ),
            )
        )
        self._default_category = default_category
        self._max_categories = max_categories

    def categorize(
        self, email: EmailEnvelope, insight: EmailInsight | None
    ) -> Sequence[EmailCategory]:
        """Return categories derived from subject, body, and metadata."""

        haystack = _build_haystack(email, insight)
        selected: list[EmailCategory] = []
        seen: set[str] = set()

        for rule in self._rules:
            if rule.key in seen:
                continue
            if _matches_rule(rule, email, insight, haystack):
                seen.add(rule.key)
                selected.append(EmailCategory(key=rule.key, label=rule.label))
                if (
                    self._max_categories is not None
                    and len(selected) >= self._max_categories
                ):
                    break

        if not selected and self._default_category is not None:
            selected.append(self._default_category)

        return tuple(selected)


def _build_haystack(email: EmailEnvelope, insight: EmailInsight | None) -> str:
    parts: list[str] = []
    if email.subject:
        parts.append(email.subject)
    if email.body.text:
        parts.append(email.body.text)
    if email.body.html:
        parts.append(email.body.html)
    if insight is not None:
        parts.append(insight.summary)
        parts.extend(insight.action_items)
    return " ".join(parts).lower()


def _matches_rule(
    rule: _CategoryRule,
    email: EmailEnvelope,
    insight: EmailInsight | None,
    haystack: str,
) -> bool:
    if rule.keywords and _contains_keyword(rule.keywords, haystack):
        return True
    if rule.predicate is not None:
        return rule.predicate(email, insight, haystack)
    return False


def _contains_keyword(keywords: Iterable[str], haystack: str) -> bool:
    for keyword in keywords:
        if keyword in haystack:
            return True
    return False


__all__ = ["KeywordCategoryService"]
