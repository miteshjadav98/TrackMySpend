"""Read one statement table from an Excel workbook without retaining the file."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from io import BytesIO
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile
from zlib import error as DecompressionError

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException
from openpyxl.worksheet._read_only import ReadOnlyWorksheet

from finance_core.errors import PayloadTooLargeError, ValidationFailedError
from finance_core.imports.cells import Cell, cell_text
from finance_core.imports.columns import (
    HEADER_SEARCH_ROWS,
    find_header_row,
    find_statement_data_header,
    header_signature,
)
from finance_core.imports.readers import NOT_A_STATEMENT
from finance_core.imports.table import MAX_DATA_ROWS, StatementTable, locate_table

_OLE_SIGNATURE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_MAX_EXPANDED_BYTES = 32 * 1024 * 1024
_MAX_SCAN_ROWS = 100_000
_MAX_COLUMNS = 256


@dataclass(frozen=True, slots=True)
class WorkbookTable:
    """The selected table and visible worksheet names in workbook order."""

    table: StatementTable
    sheet_name: str
    sheet_names: list[str]


def _sheet_rows(sheet: ReadOnlyWorksheet) -> list[list[Cell]]:
    # Some bank exporters write an incorrect dimension. Read actual cells with explicit bounds.
    sheet.reset_dimensions()
    rows: list[list[Cell]] = []
    # ReadOnlyWorksheet aliases Worksheet.iter_rows, whose stub only accepts Worksheet as self.
    for index, values in enumerate(sheet.iter_rows(values_only=True)):  # type: ignore[misc]
        if index >= _MAX_SCAN_ROWS or any(value is not None for value in values[_MAX_COLUMNS:]):
            raise PayloadTooLargeError(
                "That worksheet is too large. Export a shorter date range and try again.",
                code="worksheet_too_large",
            )
        last = next((i for i in range(len(values) - 1, -1, -1) if values[i] is not None), None)
        if last is not None:
            cells: list[Cell] = [
                value
                if value is None or isinstance(value, str | int | float | Decimal | date)
                else str(value)
                for value in values[: last + 1]
            ]
            if any(cell_text(cell) for cell in cells):
                rows.append(cells)
        if len(rows) > MAX_DATA_ROWS + HEADER_SEARCH_ROWS:
            break  # locate_table will report the usual data-row limit
    return rows


def _choose_table(
    sheets: list[ReadOnlyWorksheet],
    sheet_name: str | None,
    remembered_sheet: tuple[str, str] | None,
) -> WorkbookTable:
    by_name = {sheet.title: sheet for sheet in sheets}
    names = list(by_name)
    if sheet_name is not None:
        if sheet_name not in by_name:
            raise ValidationFailedError(
                "That worksheet is not in the workbook.", code="sheet_not_found"
            )
        return WorkbookTable(locate_table(_sheet_rows(by_name[sheet_name])), sheet_name, names)

    if remembered_sheet is not None:
        name, signature = remembered_sheet
        if name in by_name:
            try:
                table = locate_table(_sheet_rows(by_name[name]))
            except (ValidationFailedError, PayloadTooLargeError):
                pass  # Try the workbook's current layout if the remembered sheet has changed.
            else:
                if header_signature(table.headers) == signature:
                    return WorkbookTable(table, name, names)

    fallback = None
    empty_error = None
    all_empty = True
    for sheet in sheets:
        rows = _sheet_rows(sheet)
        recognizable = (
            find_header_row(rows) is not None or find_statement_data_header(rows) is not None
        )
        try:
            table = locate_table(rows)
        except ValidationFailedError as error:
            if error.code == "empty_file":
                empty_error = error
            else:
                all_empty = False
            continue
        candidate = WorkbookTable(table, sheet.title, names)
        if recognizable:
            return candidate
        all_empty = False
        if fallback is None:
            fallback = candidate
    if fallback is not None:
        return fallback
    if all_empty and empty_error is not None:
        raise empty_error
    raise ValidationFailedError(
        "I couldn't find a table of transactions in that workbook.", code=NOT_A_STATEMENT
    )


def read_workbook(
    data: bytes,
    *,
    sheet_name: str | None = None,
    remembered_sheet: tuple[str, str] | None = None,
) -> WorkbookTable:
    """Use the requested sheet, a matching remembered layout, or the first statement sheet."""
    if data.startswith(_OLE_SIGNATURE):
        raise ValidationFailedError(
            "This Excel file appears to be password-protected. Save an unlocked .xlsx copy and try again.",
            code="protected_workbook",
        )
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if any(entry.flag_bits & 1 for entry in entries):
                raise ValidationFailedError(
                    "Save an unlocked .xlsx copy and try again.", code="protected_workbook"
                )
            if sum(entry.file_size for entry in entries) > _MAX_EXPANDED_BYTES:
                raise PayloadTooLargeError(
                    "That workbook is too large. Export a shorter date range and try again.",
                    code="workbook_too_large",
                )
        with BytesIO(data) as source:
            workbook = load_workbook(source, read_only=True, data_only=True, keep_links=False)
            try:
                sheets: list[ReadOnlyWorksheet] = [
                    sheet
                    for sheet in workbook.worksheets
                    if isinstance(sheet, ReadOnlyWorksheet) and sheet.sheet_state == "visible"
                ]
                return _choose_table(sheets, sheet_name, remembered_sheet)
            finally:
                workbook.close()
    except (
        BadZipFile,
        DecompressionError,
        InvalidFileException,
        OSError,
        ParseError,
        KeyError,
        IndexError,
        TypeError,
        ValueError,
        OverflowError,
    ):
        raise ValidationFailedError(
            "This Excel file could not be read. Export a fresh .xlsx or CSV from your bank.",
            code=NOT_A_STATEMENT,
        ) from None
