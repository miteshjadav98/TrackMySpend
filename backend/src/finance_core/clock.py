"""Time source abstraction so date logic is deterministic in tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Protocol
from zoneinfo import ZoneInfo


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as an aware UTC datetime."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """Clock pinned to a moment; tests can move it forward explicitly."""

    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._moment = moment.astimezone(UTC)

    def now(self) -> datetime:
        return self._moment

    def set(self, moment: datetime) -> None:
        self._moment = moment.astimezone(UTC)


def today_in(clock: Clock, timezone: str) -> date:
    """The calendar date the user is currently living in."""
    return clock.now().astimezone(ZoneInfo(timezone)).date()
