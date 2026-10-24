"""Deterministic date resolution in the user's own calendar.

The LLM only *reads* date expressions ("yesterday", "last friday"); this module turns them
into calendar dates relative to the user's local "today". Transactions store a plain
`DATE` (the day the user experienced), so month boundaries never depend on server time.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

WEEKDAYS: dict[str, int] = {
    "monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3, "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5, "sunday": 6, "sun": 6,
}  # fmt: skip

MONTHS: dict[str, int] = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12,
}  # fmt: skip

EARLIEST_ALLOWED_DATE = date(1990, 1, 1)
MAX_RANGE_DAYS = 366 * 5

_TODAY_WORDS = {"today", "tonight", "now", "this morning", "this afternoon", "this evening"}
_YESTERDAY_WORDS = {
    "yesterday", "last night", "yesterday night", "yesterday evening",
    "yesterday morning", "yesterday afternoon", "yday", "ystd",
}  # fmt: skip
_DAY_BEFORE_WORDS = {"day before yesterday", "the day before yesterday", "day before"}

_MONTH_NAMES = "|".join(sorted(MONTHS, key=len, reverse=True))
_WEEKDAY_NAMES = "|".join(sorted(WEEKDAYS, key=len, reverse=True))

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
_NUMERIC = re.compile(r"^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?$")
_DAY_MONTH = re.compile(rf"^(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_NAMES})(?:,?\s+(\d{{4}}))?$")
_MONTH_DAY = re.compile(rf"^({_MONTH_NAMES})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?$")
_DAYS_AGO = re.compile(r"^(\d{1,3}|a|an|one|two|three|four|five|six|seven)\s+days?\s+ago$")
_WEEKS_AGO = re.compile(r"^(a|an|one|two|three|1|2|3)\s+weeks?\s+ago$")
_LAST_WEEKDAY = re.compile(rf"^(?:last|previous)\s+({_WEEKDAY_NAMES})$")
_THIS_WEEKDAY = re.compile(rf"^(?:on\s+)?(?:this\s+(?:past\s+)?)?({_WEEKDAY_NAMES})$")

_SMALL_NUMBERS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                  "six": 6, "seven": 7}  # fmt: skip


def _clean(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"^(on|at|for|dated)\s+", "", text)
    text = re.sub(r"[!?]+$", "", text)
    return re.sub(r"\s+", " ", text).strip(" .,")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _most_recent(month: int, day: int, today: date) -> date | None:
    """Day/month without a year: the most recent occurrence on or before today."""
    candidate = _safe_date(today.year, month, day)
    if candidate is not None and candidate <= today:
        return candidate
    return _safe_date(today.year - 1, month, day)


def _expand_year(year_text: str) -> int:
    year = int(year_text)
    return 2000 + year if year < 100 else year


def resolve_date_expression(text: str, today: date, *, day_first: bool = True) -> date | None:
    """Resolve a user's date expression relative to `today`. None if not understood."""
    if not text:
        return None
    expr = _clean(text)
    if expr in _TODAY_WORDS:
        return today
    if expr in _YESTERDAY_WORDS:
        return today - timedelta(days=1)
    if expr in _DAY_BEFORE_WORDS:
        return today - timedelta(days=2)

    if m := _DAYS_AGO.match(expr):
        raw = m.group(1)
        days = _SMALL_NUMBERS.get(raw) if not raw.isdigit() else int(raw)
        return today - timedelta(days=days or 0)
    if m := _WEEKS_AGO.match(expr):
        raw = m.group(1)
        weeks = int(raw) if raw.isdigit() else _SMALL_NUMBERS[raw]
        return today - timedelta(weeks=weeks)
    if m := _LAST_WEEKDAY.match(expr):
        target = WEEKDAYS[m.group(1)]
        delta = (today.weekday() - target) % 7 or 7  # strictly before today
        return today - timedelta(days=delta)
    if m := _THIS_WEEKDAY.match(expr):
        target = WEEKDAYS[m.group(1)]
        return today - timedelta(days=(today.weekday() - target) % 7)  # on or before today

    if m := _ISO.match(expr):
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    if m := _NUMERIC.match(expr):
        first, second, year_text = int(m.group(1)), int(m.group(2)), m.group(3)
        day, month = (first, second) if day_first else (second, first)
        if year_text:
            return _safe_date(_expand_year(year_text), month, day)
        return _most_recent(month, day, today)
    if m := _DAY_MONTH.match(expr):
        day, month, year_text = int(m.group(1)), MONTHS[m.group(2)], m.group(3)
        if year_text:
            return _safe_date(int(year_text), month, day)
        return _most_recent(month, day, today)
    if m := _MONTH_DAY.match(expr):
        month, day, year_text = MONTHS[m.group(1)], int(m.group(2)), m.group(3)
        if year_text:
            return _safe_date(int(year_text), month, day)
        return _most_recent(month, day, today)
    return None


def parse_iso_date(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        return None


def day_first_for_locale(locale: str) -> bool:
    """en-US writes month/day; nearly everyone else (including en-IN) writes day/month."""
    return not locale.lower().replace("_", "-").startswith("en-us")


# ---------------------------------------------------------------------------------------
# Reporting periods
# ---------------------------------------------------------------------------------------

PeriodKind = Literal[
    "today", "yesterday", "this_week", "last_week", "this_month", "last_month",
    "this_year", "last_year", "last_n_days", "month", "range",
]  # fmt: skip


@dataclass(frozen=True, slots=True)
class DateRange:
    start: date
    end: date  # inclusive
    label: str

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


class PeriodError(ValueError):
    pass


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month]} {year}"


def _fmt(day: date) -> str:
    return f"{day.day} {calendar.month_abbr[day.month]} {day.year}"


def resolve_period(
    kind: PeriodKind,
    today: date,
    *,
    month: str | None = None,
    start: str | None = None,
    end: str | None = None,
    days: int | None = None,
) -> DateRange:
    """Turn a period spec into explicit inclusive dates in the user's calendar."""
    if kind == "today":
        return DateRange(today, today, "Today")
    if kind == "yesterday":
        day = today - timedelta(days=1)
        return DateRange(day, day, "Yesterday")
    if kind == "this_week":
        monday = today - timedelta(days=today.weekday())
        return DateRange(monday, today, "This week")
    if kind == "last_week":
        this_monday = today - timedelta(days=today.weekday())
        return DateRange(
            this_monday - timedelta(days=7), this_monday - timedelta(days=1), "Last week"
        )
    if kind == "this_month":
        first, _ = month_bounds(today.year, today.month)
        return DateRange(first, today, _month_label(today.year, today.month))
    if kind == "last_month":
        year, mon = (today.year, today.month - 1) if today.month > 1 else (today.year - 1, 12)
        first, last = month_bounds(year, mon)
        return DateRange(first, last, _month_label(year, mon))
    if kind == "this_year":
        return DateRange(date(today.year, 1, 1), today, str(today.year))
    if kind == "last_year":
        year = today.year - 1
        return DateRange(date(year, 1, 1), date(year, 12, 31), str(year))
    if kind == "last_n_days":
        count = days or 30
        if not 1 <= count <= MAX_RANGE_DAYS:
            raise PeriodError("The number of days must be between 1 and 1830")
        return DateRange(today - timedelta(days=count - 1), today, f"Last {count} days")
    if kind == "month":
        if not month or not re.fullmatch(r"\d{4}-\d{2}", month):
            raise PeriodError("Month must look like YYYY-MM")
        year, mon = int(month[:4]), int(month[5:])
        if not 1 <= mon <= 12:
            raise PeriodError("Month must be between 01 and 12")
        first, last = month_bounds(year, mon)
        return DateRange(first, last, _month_label(year, mon))
    if kind == "range":
        start_date, end_date = parse_iso_date(start), parse_iso_date(end)
        if start_date is None or end_date is None:
            raise PeriodError("A custom range needs a start and an end date (YYYY-MM-DD)")
        if end_date < start_date:
            raise PeriodError("The end date must be on or after the start date")
        if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
            raise PeriodError("A custom range can cover at most 5 years")
        return DateRange(start_date, end_date, f"{_fmt(start_date)} – {_fmt(end_date)}")
    raise PeriodError(f"Unknown period: {kind}")


def format_day(day: date, today: date) -> str:
    """Friendly label: Today / Yesterday / Fri, 23 Oct (year shown when not current)."""
    if day == today:
        return "today"
    if day == today - timedelta(days=1):
        return "yesterday"
    label = f"{calendar.day_abbr[day.weekday()]}, {day.day} {calendar.month_abbr[day.month]}"
    return label if day.year == today.year else f"{label} {day.year}"
