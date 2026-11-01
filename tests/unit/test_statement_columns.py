"""Finding the table in a statement and guessing which column is which."""

from __future__ import annotations

from pathlib import Path

from finance_core.imports.cells import Cell
from finance_core.imports.columns import find_header_row, guess_columns, header_signature
from finance_core.imports.readers import read_csv

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "statements"


def _rows(name: str) -> list[list[Cell]]:
    return read_csv((FIXTURES / name).read_bytes())


def test_hdfc_style_headers_give_debit_and_credit_columns_and_ignore_the_balance() -> None:
    headers = _rows("hdfc_savings.csv")[0]
    columns = guess_columns(headers)
    assert columns.date_column == 0  # not the "Value Dt" column
    assert columns.description_column == 1
    assert columns.reference_column == 2
    assert columns.debit_column == 4
    assert columns.credit_column == 5
    assert columns.amount_column is None
    assert columns.is_usable()


def test_sbi_style_headers_skip_the_value_date_and_the_balance() -> None:
    rows = _rows("sbi_savings.csv")
    header_index = find_header_row(rows)
    assert header_index is not None
    columns = guess_columns(rows[header_index])
    assert columns.date_column == 0
    assert columns.description_column == 2
    assert (columns.debit_column, columns.credit_column) == (4, 5)


def test_one_signed_amount_column_is_found_when_there_are_no_debit_and_credit_columns() -> None:
    columns = guess_columns(["Transaction Date", "Transaction Remarks", "Amount (INR)", "Balance"])
    assert (columns.date_column, columns.description_column, columns.amount_column) == (0, 1, 2)
    assert columns.debit_column is None
    assert columns.is_usable()


def test_the_account_details_above_the_table_are_skipped() -> None:
    rows = _rows("sbi_savings.csv")
    assert find_header_row(rows) == 7
    assert rows[7][0] == "Txn Date"


def test_a_file_with_no_table_has_no_header_row() -> None:
    assert find_header_row([["hello", "world"], ["nothing", "here"]]) is None


def test_headers_that_say_nothing_give_an_unusable_guess() -> None:
    assert not guess_columns(["A", "B", "C"]).is_usable()


def test_the_header_signature_ignores_case_spacing_and_punctuation() -> None:
    first = header_signature(["Date", "Narration", "Withdrawal Amt."])
    second = header_signature([" DATE ", "narration", "Withdrawal  Amt"])
    assert first == second
    assert first != header_signature(["Date", "Narration", "Deposit Amt."])
