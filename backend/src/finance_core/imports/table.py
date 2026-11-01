"""Finding the table inside the rows a reader returned, and enforcing the size limits.

Any reader (CSV today, Excel later) hands over rows of cells; this is the one place that
decides where the table starts and whether the file is usable at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from finance_core.errors import PayloadTooLargeError, ValidationFailedError
from finance_core.imports.cells import Cell, cell_text
from finance_core.imports.columns import find_header_row
from finance_core.imports.readers import NOT_A_STATEMENT

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_DATA_ROWS = 5000
# A header row we cannot recognise still needs at least this many named columns to be a table.
MIN_FALLBACK_HEADERS = 3


@dataclass(frozen=True, slots=True)
class StatementTable:
    headers: list[Cell]
    data_rows: list[list[Cell]]  # blank lines already dropped


def check_file_size(data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise PayloadTooLargeError(
            "That file is over 5 MB. Export a shorter date range and try again.",
            code="file_too_large",
        )


def _is_blank(row: Sequence[Cell]) -> bool:
    return not any(cell_text(cell) for cell in row)


def _fallback_header_row(rows: Sequence[Sequence[Cell]]) -> int | None:
    """When no header names are recognised: the first row with several named columns, so the
    user can still pick the columns by hand."""
    for index, row in enumerate(rows[:-1]):
        if sum(1 for cell in row if cell_text(cell)) >= MIN_FALLBACK_HEADERS:
            return index
    return None


def locate_table(rows: Sequence[Sequence[Cell]]) -> StatementTable:
    """The header row and the data rows below it, or a clear error for a file we cannot use."""
    if all(_is_blank(row) for row in rows):
        raise ValidationFailedError("That file is empty.", code="empty_file")
    header_index = find_header_row(rows)
    if header_index is None:
        header_index = _fallback_header_row(rows)
    if header_index is None:
        raise ValidationFailedError(
            "I couldn't find a table of transactions in that file. "
            "Upload the statement exactly as your bank exported it.",
            code=NOT_A_STATEMENT,
        )
    data_rows = [list(row) for row in rows[header_index + 1 :] if not _is_blank(row)]
    if not data_rows:
        raise ValidationFailedError(
            "That statement has a header but no transactions.", code="empty_file"
        )
    if len(data_rows) > MAX_DATA_ROWS:
        raise PayloadTooLargeError(
            f"That statement has more than {MAX_DATA_ROWS:,} rows. "
            "Export a shorter date range and try again.",
            code="too_many_rows",
        )
    return StatementTable(headers=list(rows[header_index]), data_rows=data_rows)
