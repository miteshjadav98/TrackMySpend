"""Reading single statement cells: amounts and dates the way Indian banks write them."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from finance_core.imports.cells import Cell, guess_date_order, parse_amount, parse_date


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,23,456.78", Decimal("123456.78")),
        ("₹ 500", Decimal("500")),
        ("Rs. 1,200.50", Decimal("1200.50")),
        ("500.00 Dr", Decimal("-500.00")),
        ("500.00 Cr", Decimal("500.00")),
        ("(500)", Decimal("-500")),
        ("-250.75", Decimal("-250.75")),
        ("250.75-", Decimal("-250.75")),
        ("0.00", Decimal("0.00")),
        (1245.5, Decimal("1245.5")),
        (Decimal("10"), Decimal("10")),
    ],
)
def test_amounts_are_read_the_way_indian_banks_write_them(text: Cell, expected: Decimal) -> None:
    assert parse_amount(text) == expected


@pytest.mark.parametrize("blank", ["", "   ", "-", None])
def test_a_blank_amount_cell_is_no_amount(blank: Cell) -> None:
    assert parse_amount(blank) is None


def test_text_in_an_amount_cell_is_an_error_not_a_zero() -> None:
    with pytest.raises(ValueError, match="amount"):
        parse_amount("Opening Balance")


def test_the_same_numeric_date_reads_differently_day_first_and_month_first() -> None:
    assert parse_date("03/04/2026", day_first=True) == date(2026, 4, 3)
    assert parse_date("03/04/2026", day_first=False) == date(2026, 3, 4)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("01/10/26", date(2026, 10, 1)),
        ("1 Oct 2026", date(2026, 10, 1)),
        ("01-Oct-2026", date(2026, 10, 1)),
        ("2026-10-01", date(2026, 10, 1)),
        ("01.10.2026", date(2026, 10, 1)),
        ("2026-10-01 14:30:00", date(2026, 10, 1)),
        (date(2026, 10, 1), date(2026, 10, 1)),
    ],
)
def test_common_bank_date_spellings_are_understood(text: Cell, expected: date) -> None:
    assert parse_date(text, day_first=True) == expected


def test_an_impossible_date_is_an_error() -> None:
    with pytest.raises(ValueError, match="date"):
        parse_date("31/02/2026", day_first=True)


def test_a_day_above_twelve_in_the_first_slot_settles_the_date_order() -> None:
    assert guess_date_order(["13/01/2026", "02/01/2026"]) == "day_first"
    assert guess_date_order(["01/13/2026", "01/02/2026"]) == "month_first"


def test_an_ambiguous_column_defaults_to_day_first() -> None:
    assert guess_date_order(["03/04/2026", "05/06/2026"]) == "day_first"
