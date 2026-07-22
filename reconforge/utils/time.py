"""Timezone-aware UTC helpers for stable local artifact timestamps."""

from __future__ import annotations

from datetime import UTC, date, datetime


def utc_now_text() -> str:
    """Return second-precision RFC 3339 UTC text with the established Z suffix."""

    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def utc_today() -> date:
    """Return the current UTC calendar date."""

    return datetime.now(UTC).date()
