from __future__ import annotations

from datetime import date

from finance_core.dates import DateRange, preceding_period
from finance_core.reports.service import trend_ranges


def test_preceding_period_has_equal_length_and_touches_requested_period() -> None:
    current = DateRange(date(2026, 10, 1), date(2026, 10, 24), "October 2026")

    previous = preceding_period(current)

    assert previous.start == date(2026, 9, 7)
    assert previous.end == date(2026, 9, 30)
    assert previous.days == current.days == 24


def test_trend_ranges_choose_bounded_day_week_and_month_buckets() -> None:
    day_kind, days = trend_ranges(DateRange(date(2026, 10, 1), date(2026, 10, 3), "three"))
    week_kind, weeks = trend_ranges(DateRange(date(2026, 1, 1), date(2026, 4, 1), "ninety"))
    month_kind, months = trend_ranges(DateRange(date(2025, 1, 15), date(2026, 6, 20), "long"))

    assert day_kind == "day"
    assert [(item.start, item.end) for item in days] == [
        (date(2026, 10, 1), date(2026, 10, 1)),
        (date(2026, 10, 2), date(2026, 10, 2)),
        (date(2026, 10, 3), date(2026, 10, 3)),
    ]
    assert week_kind == "week"
    assert weeks[0].start == date(2026, 1, 1)
    assert weeks[-1].end == date(2026, 4, 1)
    assert len(weeks) == 13
    assert month_kind == "month"
    assert months[0] == DateRange(date(2025, 1, 15), date(2025, 1, 31), "Jan 2025")
    assert months[-1] == DateRange(date(2026, 6, 1), date(2026, 6, 20), "Jun 2026")
    assert len(months) == 18
