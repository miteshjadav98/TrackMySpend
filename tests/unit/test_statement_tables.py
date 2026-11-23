"""Recognising the transaction table beneath statement account details."""

from datetime import date, datetime
from io import BytesIO

import pytest
from openpyxl import Workbook

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
