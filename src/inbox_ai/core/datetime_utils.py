"""Datetime helpers shared across the application."""

from __future__ import annotations

from datetime import UTC, datetime

__all__ = [
    "serialize_datetime",
    "parse_datetime",
    "display_datetime",
    "ensure_utc",
]


def ensure_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` converted to UTC when timezone-aware."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC)


def serialize_datetime(value: datetime | None) -> str | None:
    """Serialise ``value`` to ISO 8601, normalising timezone-aware values."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone().isoformat()


def parse_datetime(value: str | None, *, assume_utc: bool = False) -> datetime | None:
    """Parse an ISO 8601 string into a ``datetime`` instance."""
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None and assume_utc:
        return parsed.replace(tzinfo=UTC)
    return parsed


def display_datetime(value: datetime | None) -> str | None:
    """Return a user-friendly representation of ``value`` for templates."""
    if value is None:
        return None
    display = ensure_utc(value) or value
    return display.astimezone().strftime("%b %d, %Y %I:%M %p")
