"""File readers: turn an uploaded file into rows of cells.

Every reader returns the same shape, `list[list[Cell]]`, so the parser does not care whether a
statement came from a CSV or (later) an Excel sheet. The reader only reads; finding the table
and the columns is the parser's job.
"""

from __future__ import annotations

import csv
import io

from finance_core.errors import ValidationFailedError
from finance_core.imports.cells import Cell

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
    """The delimiter that splits the first lines into the most cells."""
    sample = "\n".join(text.splitlines()[:30])
    try:
        return csv.Sniffer().sniff(sample, delimiters=_DELIMITERS).delimiter
    except csv.Error:
        return ","


def read_csv(data: bytes) -> list[list[Cell]]:
    """All rows of a CSV file, cells as text."""
    if b"\x00" in data[:4096] or data.startswith(b"PK"):
        # NUL bytes mean a binary file; "PK" is a zip, which is what .xlsx is.
        raise ValidationFailedError(
            "This does not look like a CSV statement. Excel files are not supported yet.",
            code=NOT_A_STATEMENT,
        )
    text = _decode(data)
    reader = csv.reader(io.StringIO(text), delimiter=_delimiter(text))
    return [list(row) for row in reader]
