"""Finding a statement's table and guessing which column is which, from the header row.

Pure functions. The guess only reads header names; the user confirms it once and the
confirmed layout is remembered per account (see the service).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

from finance_core.imports.cells import Cell, cell_text, parse_amount, parse_date
from finance_core.imports.schemas import ColumnMap

# How far down a file the table may start: bank statements put a few lines of account
# details above it.
HEADER_SEARCH_ROWS = 60
MIN_FALLBACK_HEADERS = 3


def normalise_header(cell: Cell) -> str:
    """A header in lower case with punctuation and extra spaces removed."""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", cell_text(cell).lower()).split())


def header_signature(headers: Sequence[Cell]) -> str:
    """A short fingerprint of the header row, to recognise the same bank's next statement."""
    names = [normalise_header(cell) for cell in headers]
    while names and not names[-1]:
        names.pop()
    return hashlib.sha256("|".join(names).encode()).hexdigest()[:32]


def _role(header: str) -> str | None:
    words = header.split()
    if "balance" in words or "bal" in words:
        return "balance"  # never an amount
    if "value" in words and ("date" in words or "dt" in words):
        return "value_date"
    if "date" in words or "dt" in words:
        return "date"
    if header in ("dr", "cr", "dr cr", "cr dr"):
        return None  # a Dr/Cr marker column, not an amount
    if any(word in words for word in ("debit", "withdrawal", "withdrawals", "withdrawn", "dr")):
        return "debit"
    if any(word in words for word in ("credit", "deposit", "deposits", "cr")):
        return "credit"
    if "amount" in words or "amt" in words:
        return "amount"
    if any(
        word in words for word in ("narration", "description", "particulars", "remarks", "details")
    ):
        return "description"
    if any(word in words for word in ("ref", "chq", "cheque", "reference", "utr")):
        return "reference"
    return None


def guess_columns(headers: Sequence[Cell]) -> ColumnMap:
    """The first column of each role. Debit and credit columns win over a single amount."""
    first: dict[str, int] = {}
    for index, cell in enumerate(headers):
        role = _role(normalise_header(cell))
        if role and role not in first:
            first[role] = index
    use_debit_credit = "debit" in first and "credit" in first
    return ColumnMap(
        date_column=first.get("date", first.get("value_date")),
        description_column=first.get("description"),
        amount_column=None if use_debit_credit else first.get("amount"),
        debit_column=first.get("debit") if use_debit_credit else None,
        credit_column=first.get("credit") if use_debit_credit else None,
        reference_column=first.get("reference"),
    )


def find_header_row(rows: Sequence[Sequence[Cell]]) -> int | None:
    """The first row whose headers give a usable guess, or None if the file has no table."""
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        if guess_columns(row).is_usable():
            return index
    return None


def find_statement_data_header(rows: Sequence[Sequence[Cell]]) -> int | None:
    """Find an unfamiliar header above rows with a date and amount in named columns."""
    for index, header in enumerate(rows[:HEADER_SEARCH_ROWS]):
        if sum(bool(cell_text(cell)) for cell in header) < MIN_FALLBACK_HEADERS:
            continue
        if _has_date_and_amount(header) or not all(
            isinstance(cell, str) or not cell_text(cell) for cell in header
        ):
            continue
        next_row = next(
            (row for row in rows[index + 1 : index + 6] if any(cell_text(cell) for cell in row)),
            (),
        )
        named_cells = [
            cell for name, cell in zip(header, next_row, strict=False) if cell_text(name)
        ]
        if _has_date_and_amount(named_cells):
            return index
    return None


def _has_date_and_amount(cells: Sequence[Cell]) -> bool:
    has_date = has_amount = False
    for cell in cells:
        if _looks_like_date(cell):
            has_date = True
        else:
            try:
                amount = parse_amount(cell)
            except ValueError:
                continue
            has_amount = has_amount or (amount is not None and amount.is_finite())
        if has_date and has_amount:
            return True
    return False


def _looks_like_date(cell: Cell) -> bool:
    for day_first in (True, False):
        try:
            parse_date(cell, day_first=day_first)
        except ValueError:
            continue
        return True
    return False
