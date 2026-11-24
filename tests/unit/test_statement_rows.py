"""Turning a statement's data rows into dated, signed amounts."""

from __future__ import annotations

from datetime import date

from finance_core.imports.cells import Cell
from finance_core.imports.rows import ParsedRow, parse_data_rows
from finance_core.imports.schemas import ColumnMap

TODAY = date(2026, 10, 24)

DEBIT_CREDIT = ColumnMap(
    date_column=0, description_column=1, debit_column=2, credit_column=3, date_order="day_first"
)
SIGNED = ColumnMap(date_column=0, description_column=1, amount_column=2, date_order="day_first")


def _parse(rows: list[list[Cell]], columns: ColumnMap) -> list[ParsedRow]:
    return parse_data_rows(rows, columns, currency="INR", today=TODAY)


def test_a_debit_is_money_out_and_a_credit_is_money_in() -> None:
    out, money_in = _parse(
        [["01/10/2026", "Swiggy", "450.00", ""], ["05/10/2026", "Salary", "", "1,23,456.78"]],
        DEBIT_CREDIT,
    )
    assert (out.direction, out.amount_minor, out.occurred_on) == ("out", 45000, date(2026, 10, 1))
    assert (money_in.direction, money_in.amount_minor) == ("in", 12345678)


def test_a_signed_amount_column_uses_the_sign_for_direction() -> None:
    out, money_in = _parse(
        [["01/10/2026", "Swiggy", "-450.00"], ["02/10/2026", "Refund", "99.50"]], SIGNED
    )
    assert (out.direction, out.amount_minor) == ("out", 45000)
    assert (money_in.direction, money_in.amount_minor) == ("in", 9950)


def test_dr_and_cr_suffixes_decide_direction_in_a_single_amount_column() -> None:
    out, money_in = _parse(
        [["01/10/2026", "Rent", "500.00 Dr"], ["02/10/2026", "Interest", "12.00 Cr"]], SIGNED
    )
    assert out.direction == "out"
    assert money_in.direction == "in"


def test_blank_lines_are_dropped_and_unreadable_rows_keep_a_reason() -> None:
    rows = _parse(
        [
            ["", "", "", ""],
            ["01/10/2026", "Swiggy", "450.00", ""],
            ["Closing balance", "", "", ""],
            ["02/10/2026", "Odd", "abc", ""],
            ["03/10/2026", "Neither", "", ""],
        ],
        DEBIT_CREDIT,
    )
    assert [row.problem is None for row in rows] == [True, False, False, False]
    assert "date" in (rows[1].problem or "")
    assert "amount" in (rows[2].problem or "")
    assert rows[3].problem


def test_a_date_in_the_future_is_a_problem_row() -> None:
    [row] = _parse([["25/10/2026", "Tomorrow", "10.00", ""]], DEBIT_CREDIT)
    assert "future" in (row.problem or "")


def test_a_zero_amount_row_is_a_problem_row() -> None:
    [row] = _parse([["01/10/2026", "Waived fee", "0.00", ""]], DEBIT_CREDIT)
    assert row.problem


def test_more_decimals_than_the_currency_allows_is_a_problem_not_a_rounding() -> None:
    [row] = _parse([["01/10/2026", "Odd", "10.005", ""]], DEBIT_CREDIT)
    assert row.problem


def test_positions_count_data_rows_from_one_including_dropped_blanks() -> None:
    rows = _parse([["", "", "", ""], ["01/10/2026", "A", "1.00", ""]], DEBIT_CREDIT)
    assert [row.position for row in rows] == [2]
