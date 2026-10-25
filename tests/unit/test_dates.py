from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from finance_core.clock import FixedClock, today_in
from finance_core.dates import (
    PeriodError,
    format_day,
    resolve_date_expression,
    resolve_period,
)

SATURDAY = date(2026, 10, 24)


def span(period: object) -> tuple[date, date]:
    return period.start, period.end  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("today", "2026-10-24"),
        ("yesterday", "2026-10-23"),
        ("last night", "2026-10-23"),
        ("day before yesterday", "2026-10-22"),
        ("3 days ago", "2026-10-21"),
        ("a week ago", "2026-10-17"),
        ("last friday", "2026-10-23"),
        ("last saturday", "2026-10-17"),  # strictly before today
        ("on friday", "2026-10-23"),
        ("saturday", "2026-10-24"),  # on or before today
        ("12 oct", "2026-10-12"),
        ("oct 12", "2026-10-12"),
        ("12th of october 2025", "2025-10-12"),
        ("25 dec", "2025-12-25"),  # day/month without a year: most recent past occurrence
        ("23/10/2026", "2026-10-23"),
        ("12/10", "2026-10-12"),
        ("2026-10-01", "2026-10-01"),
    ],
)
def test_resolve_date_expression(text: str, expected: str) -> None:
    assert resolve_date_expression(text, SATURDAY) == date.fromisoformat(expected)


def test_month_first_locales() -> None:
    assert resolve_date_expression("10/12", SATURDAY, day_first=False) == date(2026, 10, 12)
    assert resolve_date_expression("10/12", SATURDAY, day_first=True) == date(2025, 12, 10)


@pytest.mark.parametrize("text", ["sometime", "31/02/2026", "", "next week"])
def test_unresolvable_expressions_return_none(text: str) -> None:
    assert resolve_date_expression(text, SATURDAY) is None


def test_today_follows_the_users_timezone() -> None:
    # 20:00 UTC on the 24th is already the 25th in India.
    clock = FixedClock(datetime(2026, 10, 24, 20, 0, tzinfo=UTC))
    assert today_in(clock, "Asia/Kolkata") == date(2026, 10, 25)
    assert today_in(clock, "America/New_York") == date(2026, 10, 24)


def test_periods() -> None:
    assert span(resolve_period("this_month", SATURDAY)) == (date(2026, 10, 1), SATURDAY)
    assert span(resolve_period("last_month", SATURDAY)) == (date(2026, 9, 1), date(2026, 9, 30))
    assert span(resolve_period("last_month", date(2026, 1, 15))) == (
        date(2025, 12, 1),
        date(2025, 12, 31),
    )
    assert span(resolve_period("this_week", SATURDAY)) == (date(2026, 10, 19), SATURDAY)
    assert span(resolve_period("last_week", SATURDAY)) == (date(2026, 10, 12), date(2026, 10, 18))
    assert span(resolve_period("last_n_days", SATURDAY, days=7)) == (date(2026, 10, 18), SATURDAY)
    assert span(resolve_period("month", SATURDAY, month="2024-02")) == (
        date(2024, 2, 1),
        date(2024, 2, 29),
    )
    assert resolve_period("month", SATURDAY, month="2026-09").label == "September 2026"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "month", "month": "2026-13"},
        {"kind": "month", "month": "October"},
        {"kind": "range", "start": "2026-10-10", "end": "2026-10-01"},
        {"kind": "range", "start": "2010-01-01", "end": "2026-01-01"},
        {"kind": "last_n_days", "days": 0},
    ],
)
def test_invalid_periods(kwargs: dict) -> None:
    kind = kwargs.pop("kind")
    with pytest.raises(PeriodError):
        resolve_period(kind, SATURDAY, **kwargs)


def test_format_day() -> None:
    assert format_day(SATURDAY, SATURDAY) == "today"
    assert format_day(date(2026, 10, 23), SATURDAY) == "yesterday"
    assert format_day(date(2026, 10, 20), SATURDAY) == "Tue, 20 Oct"
    assert format_day(date(2025, 10, 20), SATURDAY) == "Mon, 20 Oct 2025"
