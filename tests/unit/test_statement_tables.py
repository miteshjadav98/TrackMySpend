"""Recognising the transaction table beneath statement account details."""

from datetime import date, datetime
from io import BytesIO

import pytest
from openpyxl import Workbook

from finance_core.errors import ValidationFailedError
from finance_core.imports.readers import read_csv
from finance_core.imports.table import locate_table
from finance_core.imports.workbook import read_workbook


@pytest.mark.parametrize("preamble_lines", [0, 5, 15])
def test_csv_preamble_does_not_hide_a_semicolon_delimited_table(preamble_lines: int) -> None:
    preamble = "Statement details, savings account\n" * preamble_lines
    data = (preamble + 'Date;Description;Amount\n03/10/2026;"Tea, coffee";-250.50\n').encode()

    table = locate_table(read_csv(data))

    assert table.headers == ["Date", "Description", "Amount"]
    assert table.data_rows == [["03/10/2026", "Tea, coffee", "-250.50"]]


@pytest.mark.parametrize("preamble_lines", [0, 5, 15])
def test_excel_preamble_does_not_hide_the_table_or_change_native_cells(preamble_lines: int) -> None:
    book = Workbook()
    sheet = book.active
    assert sheet is not None
    for _ in range(preamble_lines):
        sheet.append(["Statement details", "Savings account"])
    sheet.append(["Date", "Description", "Amount"])
    sheet.append([date(2026, 10, 3), "Tea", -250.5])
    with BytesIO() as file:
        book.save(file)
        table = read_workbook(file.getvalue()).table

    assert table.headers == ["Date", "Description", "Amount"]
    assert table.data_rows == [[datetime(2026, 10, 3), "Tea", -250.5]]


def test_csv_finds_a_delimiter_even_when_the_headers_need_manual_mapping() -> None:
    data = b"Savings statement, October\nAccount, 1234\nBooked;Memo;Net\n03/10/2026;Tea;-250.50\n"

    table = locate_table(read_csv(data))

    assert table.headers == ["Booked", "Memo", "Net"]
    assert table.data_rows == [["03/10/2026", "Tea", "-250.50"]]


def test_excel_uses_the_first_real_table_even_if_it_needs_manual_mapping() -> None:
    book = Workbook()
    assert book.active is not None
    book.active.append(["Statement", "Account", "Dates"])
    book.active.append(["Savings", "1234", "January"])
    first = book.create_sheet("January")
    first.append(["Booked", "Memo", "Net"])
    first.append([date(2026, 1, 3), "Tea", -250.5])
    second = book.create_sheet("February")
    second.append(["Date", "Description", "Amount"])
    second.append([date(2026, 2, 3), "Coffee", -150])
    with BytesIO() as file:
        book.save(file)
        selected = read_workbook(file.getvalue())

    assert selected.sheet_name == "January"
    assert selected.table.headers == ["Booked", "Memo", "Net"]


@pytest.mark.parametrize("with_header", [False, True])
def test_excel_reports_an_empty_workbook(with_header: bool) -> None:
    book = Workbook()
    if with_header:
        assert book.active is not None
        book.active.append(["Date", "Description", "Amount"])
    with BytesIO() as file:
        book.save(file)
        with pytest.raises(ValidationFailedError) as raised:
            read_workbook(file.getvalue())

    assert raised.value.code == "empty_file"
