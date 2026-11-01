"""Reading a statement's data rows into dated, signed amounts under a chosen layout.

Pure functions. A row that cannot be read is kept with a reason (`problem`) instead of being
dropped or guessed, so the preview can show it as skipped and nothing vanishes silently.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finance_core.dates import EARLIEST_ALLOWED_DATE
from finance_core.imports.cells import Cell, cell_text, parse_amount, parse_date
from finance_core.imports.schemas import ColumnMap, DirectionField
from finance_core.money import MoneyError, to_minor


@dataclass(frozen=True, slots=True)
class ParsedRow:
    """One data row of the statement. Either every field is set, or `problem` says why not."""

    position: int  # 1-based among the data rows, counting dropped blank lines
    raw_cells: list[str]
    occurred_on: date | None
    amount_minor: int | None
    direction: DirectionField | None
    description: str | None
    reference: str | None
    problem: str | None


def _cell_at(row: Sequence[Cell], column: int | None) -> Cell:
    return row[column] if column is not None and column < len(row) else None


def _signed_amount(row: Sequence[Cell], columns: ColumnMap) -> Decimal | None:
    """Money out is negative, money in is positive; None when the row has no amount."""
    if columns.debit_column is not None and columns.credit_column is not None:
        debit = parse_amount(_cell_at(row, columns.debit_column))
        credit = parse_amount(_cell_at(row, columns.credit_column))
        if debit and credit:
            raise ValueError("The row has both a debit and a credit")
        if debit:
            return -abs(debit)
        if credit:
            return abs(credit)
        return Decimal(0) if debit is not None or credit is not None else None
    return parse_amount(_cell_at(row, columns.amount_column))


def _parse_row(
    position: int, row: Sequence[Cell], columns: ColumnMap, currency: str, today: date
) -> ParsedRow:
    raw = [cell_text(cell) for cell in row]
    description = cell_text(_cell_at(row, columns.description_column)) or None
    reference = cell_text(_cell_at(row, columns.reference_column)) or None

    def unreadable(problem: str) -> ParsedRow:
        return ParsedRow(position, raw, None, None, None, description, reference, problem)

    try:
        occurred_on = parse_date(
            _cell_at(row, columns.date_column), day_first=columns.date_order == "day_first"
        )
    except ValueError:
        return unreadable("No date I can read, so this is probably not a transaction")
    if occurred_on > today:
        return unreadable("The date is in the future")
    if occurred_on < EARLIEST_ALLOWED_DATE:
        return unreadable("The date is too far in the past")
    try:
        signed = _signed_amount(row, columns)
    except ValueError as error:
        return unreadable(f"Cannot read the amount: {error}")
    if signed is None:
        return unreadable("No amount on this row")
    try:
        amount_minor = to_minor(abs(signed), currency)
    except MoneyError as error:
        return unreadable(f"Cannot read the amount: {error}")
    if amount_minor == 0:
        return unreadable("The amount is zero")
    return ParsedRow(
        position=position,
        raw_cells=raw,
        occurred_on=occurred_on,
        amount_minor=amount_minor,
        direction="out" if signed < 0 else "in",
        description=description,
        reference=reference,
        problem=None,
    )


def parse_data_rows(
    rows: Sequence[Sequence[Cell]], columns: ColumnMap, *, currency: str, today: date
) -> list[ParsedRow]:
    """Read every non-blank data row (the rows below the header) under this layout."""
    return [
        _parse_row(position, row, columns, currency, today)
        for position, row in enumerate(rows, start=1)
        if any(cell_text(cell) for cell in row)
    ]
