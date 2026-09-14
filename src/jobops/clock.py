"""The world's frozen clock.

Nothing in this package is allowed to call datetime.now(). Time is part of the
seeded world state, so a task about "applications older than 7 days" means the
same thing today, next month, and on someone else's machine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

ISO = "%Y-%m-%dT%H:%M:%SZ"

# Every world starts here. A constant, not a function of the seed, so that
# "7 days ago" is comparable across every seed and every task.
WORLD_EPOCH = datetime(2026, 9, 14, 9, 0, 0, tzinfo=timezone.utc)


def fmt(dt: datetime) -> str:
    """Datetime -> the one timestamp format this world uses."""
    return dt.astimezone(timezone.utc).strftime(ISO)


def parse(ts: str) -> datetime:
    """Timestamp string -> datetime."""
    return datetime.strptime(ts, ISO).replace(tzinfo=timezone.utc)


def days_before(dt: datetime, days: float) -> datetime:
    return dt - timedelta(days=days)


def days_between(earlier: str, later: str) -> float:
    """Whole and fractional days from one timestamp to another."""
    return (parse(later) - parse(earlier)).total_seconds() / 86400.0


class Clock:
    """A clock that only moves when the world tells it to."""

    def __init__(self, now: datetime = WORLD_EPOCH) -> None:
        self._now = now

    @property
    def now(self) -> datetime:
        return self._now

    def iso(self) -> str:
        return fmt(self._now)

    def advance(self, *, minutes: float = 0, days: float = 0) -> None:
        self._now = self._now + timedelta(minutes=minutes, days=days)

    def ago(self, days: float) -> str:
        """Timestamp for `days` before the current world time."""
        return fmt(days_before(self._now, days))
