"""Reading single statement cells: text, amounts and dates as Indian banks write them.

Pure functions with no database. A cell is whatever a file reader hands over: text from a
CSV, or numbers and dates from an Excel sheet.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from finance_core.dates import MONTHS

Cell = str | int | float | Decimal | date | datetime | None
DateOrder = Literal["day_first", "month_first"]


def cell_text(cell: Cell) -> str:
    """The cell as plain text, so rows can be stored and re-read under another layout."""
    if cell is None:
        return ""
    if isinstance(cell, datetime):
        return cell.date().isoformat()
    if isinstance(cell, date):
        return cell.isoformat()
    return str(cell).strip()


# "(500)", "-500", "500-", "500.00 Dr", "₹ 1,23,456.78": sign marks and a currency prefix are
# peeled off first, so what is left is plain digits.
_PLAIN_NUMBER = re.compile(r"([-+]?)(\d+(?:\.\d+)?|\.\d+)(-?)(dr|cr)?\.?")
_CURRENCY_PREFIX = re.compile(r"^([-+(]*)(?:₹|inr|rs\.?)")


def parse_amount(cell: Cell) -> Decimal | None:
    """A signed amount: negative for "(500)", "-500", "500-" and "Dr". None for a blank cell.

    Raises ValueError for text that is not an amount, so a footer line is never read as zero.
    """
    if isinstance(cell, int | float | Decimal):
        return Decimal(str(cell))
    text = cell_text(cell).lower()
    if text in ("", "-"):
        return None
    text = re.sub(r"[\s,]", "", text)
    text = _CURRENCY_PREFIX.sub(r"\1", text)
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    found = _PLAIN_NUMBER.fullmatch(text)
    if found is None:
        raise ValueError(f"'{cell_text(cell)}' is not an amount")
    sign, digits, trailing_minus, mark = found.groups()
    try:
        value = Decimal(digits)
    except InvalidOperation:
        raise ValueError(f"'{cell_text(cell)}' is not an amount") from None
    if negative or sign == "-" or trailing_minus or mark == "dr":
        value = -value
    return value


_ISO_DATE = re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})")
_NUMERIC_DATE = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4}|\d{2})")
_WORDY_DATE = re.compile(r"(\d{1,2})[\s/.-]+([a-z]{3,9})[\s,/.-]+(\d{4}|\d{2})")
_TIME_SUFFIX = re.compile(r"[T\s]+\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?$")


def _full_year(year: int) -> int:
    return year + 2000 if year < 100 else year


def parse_date(cell: Cell, *, day_first: bool) -> date:
    """A date from the spellings banks use. Raises ValueError for anything else."""
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    text = _TIME_SUFFIX.sub("", cell_text(cell).lower())
    try:
        if found := _ISO_DATE.fullmatch(text):
            return date(int(found[1]), int(found[2]), int(found[3]))
        if found := _NUMERIC_DATE.fullmatch(text):
            first, second = int(found[1]), int(found[2])
            day, month = (first, second) if day_first else (second, first)
            return date(_full_year(int(found[3])), month, day)
        if (found := _WORDY_DATE.fullmatch(text)) and found[2] in MONTHS:
            return date(_full_year(int(found[3])), MONTHS[found[2]], int(found[1]))
    except ValueError:
        pass  # an impossible date such as 31/02 falls through to the error below
    raise ValueError(f"'{cell_text(cell)}' is not a date I can read")


def guess_date_order(cells: list[Cell]) -> DateOrder:
    """Day-first unless a value proves month-first (a second part above 12, a first at most 12).

    Indian statements are day-first, so an ambiguous column such as 03/04/2026 stays day-first.
    """
    for cell in cells:
        found = _NUMERIC_DATE.fullmatch(cell_text(cell).lower())
        if found and int(found[1]) > 12:
            return "day_first"
    for cell in cells:
        found = _NUMERIC_DATE.fullmatch(cell_text(cell).lower())
        if found and int(found[2]) > 12:
            return "month_first"
    return "day_first"
