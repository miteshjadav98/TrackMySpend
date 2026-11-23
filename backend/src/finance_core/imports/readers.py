"""File readers: turn an uploaded file into rows of cells.

CSV cells are text. The column guess helps distinguish delimiters even when a bank's
preamble does not use the delimiter consistently.
"""

from __future__ import annotations

import csv
import io
from itertools import islice

from finance_core.errors import ValidationFailedError
from finance_core.imports.cells import Cell
from finance_core.imports.columns import HEADER_SEARCH_ROWS, find_header_row

NOT_A_STATEMENT = "not_a_statement"
_DELIMITERS = ",;\t|"


def _decode(data: bytes) -> str:
    # Banks export CSVs as UTF-8 (often with a BOM) or as Windows-1252.
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValidationFailedError("This does not look like a statement file.", code=NOT_A_STATEMENT)


def _delimiter(text: str) -> str:
    """Prefer a delimiter that gives us a recognizable statement header."""
    for delimiter in _DELIMITERS:
        try:
            rows = list(
                islice(csv.reader(io.StringIO(text), delimiter=delimiter), HEADER_SEARCH_ROWS)
            )
        except csv.Error:
            continue
        if find_header_row(rows) is not None:
            return delimiter
    sample = "\n".join(text.splitlines()[:30])
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
    except csv.Error:
        return ","


def read_csv(data: bytes) -> list[list[Cell]]:
    """All rows of a CSV file, cells as text."""
    if b"\x00" in data:
        raise ValidationFailedError(
            "This does not look like a CSV statement.",
            code=NOT_A_STATEMENT,
        )
    text = _decode(data)
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(text))
    try:
        return [list(row) for row in reader]
    except csv.Error:
        raise ValidationFailedError(
            "This CSV could not be read. Export it again from your bank.", code=NOT_A_STATEMENT
        ) from None
