"""What the imports API accepts and returns."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from finance_core.accounts.schemas import AccountRef
from finance_core.categories.schemas import CategoryRef
from finance_core.schemas import ApiInput, ApiModel

DateOrderField = Literal["day_first", "month_first"]
ImportStatusField = Literal["previewing", "imported", "undone"]
# What will happen to a preview row. Likely duplicates and transfers are filled by later
# steps (duplicate detection, transfer suggestions); every row starts as to_import or skipped.
RowStatusField = Literal["to_import", "skipped", "likely_duplicate", "transfer"]
# Where a row's category came from; the preview shows it so a guess can be told from a rule.
CategorySourceField = Literal["rule", "ai", "keyword", "default", "user"]
DirectionField = Literal["out", "in"]


class ColumnMap(ApiModel):
    """Which column (counted from 0) holds what: the statement layout of an account."""

    date_column: int | None = Field(default=None, ge=0)
    description_column: int | None = Field(default=None, ge=0)
    # One signed amount column, or separate debit and credit columns.
    amount_column: int | None = Field(default=None, ge=0)
    debit_column: int | None = Field(default=None, ge=0)
    credit_column: int | None = Field(default=None, ge=0)
    reference_column: int | None = Field(default=None, ge=0)
    date_order: DateOrderField = "day_first"

    def is_usable(self) -> bool:
        """Enough to read a row: a date, and an amount (or both debit and credit)."""
        has_amounts = self.amount_column is not None or (
            self.debit_column is not None and self.credit_column is not None
        )
        return self.date_column is not None and has_amounts

    def used_columns(self) -> list[int]:
        columns = (
            self.date_column, self.description_column, self.amount_column,
            self.debit_column, self.credit_column, self.reference_column,
        )  # fmt: skip
        return [column for column in columns if column is not None]


class ColumnMapInput(ColumnMap, ApiInput):
    """The layout the user confirmed or corrected."""


class ImportSummary(ApiModel):
    id: uuid.UUID
    account: AccountRef
    file_name: str
    status: ImportStatusField
    currency: str
    row_count: int
    imported_count: int
    skipped_count: int
    created_at: datetime
    expires_at: datetime | None
    confirmed_at: datetime | None
    undone_at: datetime | None


class PreviewCounts(ApiModel):
    """The numbers at the top of the preview. Totals are summed by the database."""

    to_import: int
    skipped: int
    likely_duplicates: int
    transfers: int
    selected: int
    selected_out_minor: int
    selected_in_minor: int


class PreviewRow(ApiModel):
    id: uuid.UUID
    position: int
    occurred_on: date | None
    direction: DirectionField | None
    amount: Decimal | None
    amount_minor: int | None
    amount_formatted: str | None
    description: str | None
    merchant: str | None
    category: CategoryRef | None
    category_source: CategorySourceField | None
    status: RowStatusField
    # Why a row is skipped or flagged, in words for the user.
    note: str | None
    is_selected: bool


class ImportDetail(ImportSummary):
    """An import with its detected layout, a few raw rows to check it against, and a page of
    preview rows."""

    headers: list[str]
    sample_rows: list[list[str]]
    layout: ColumnMap
    # False until the user confirms a layout the first time for this account's statement shape.
    layout_confirmed: bool
    counts: PreviewCounts
    rows: list[PreviewRow]
    rows_total: int


class RowChange(ApiInput):
    """One preview row edited: ticked or unticked, or filed under another category."""

    id: uuid.UUID
    is_selected: bool | None = None
    category_id: uuid.UUID | None = None


class RowChanges(ApiInput):
    rows: list[RowChange] = Field(min_length=1, max_length=5000)
