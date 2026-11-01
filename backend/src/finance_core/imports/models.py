"""The statement_imports, statement_import_rows and statement_layouts tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import (
    SCHEMA_IDENTITY,
    SCHEMA_LEDGER,
    Base,
    created_at_column,
    updated_at_column,
    uuid_pk,
)

IMPORT_STATUSES = ("previewing", "imported", "undone")
ROW_STATUSES = ("to_import", "skipped", "likely_duplicate", "transfer")
CATEGORY_SOURCES = ("rule", "ai", "keyword", "default", "user")
DATE_ORDERS = ("day_first", "month_first")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class StatementLayout(Base):
    """Which column holds what in an account's statement, remembered after the user confirms it."""

    __tablename__ = "statement_layouts"
    __table_args__ = (
        # One remembered layout per account.
        UniqueConstraint("account_id", name="uq_statement_layouts_account"),
        CheckConstraint(_in_list("date_order", DATE_ORDERS), name="date_order"),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA_LEDGER}.accounts.id"))
    # Recognises the same bank's next statement; when it differs the layout is asked again.
    header_signature: Mapped[str] = mapped_column(String(64))
    date_column: Mapped[int] = mapped_column(Integer)
    description_column: Mapped[int | None] = mapped_column(Integer)
    amount_column: Mapped[int | None] = mapped_column(Integer)
    debit_column: Mapped[int | None] = mapped_column(Integer)
    credit_column: Mapped[int | None] = mapped_column(Integer)
    reference_column: Mapped[int | None] = mapped_column(Integer)
    date_order: Mapped[str] = mapped_column(String(16))
    # For Excel statements with several sheets; unused for CSV.
    sheet_name: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class StatementImport(Base):
    """One upload of a statement into one account. The file itself is never stored."""

    __tablename__ = "statement_imports"
    __table_args__ = (
        CheckConstraint(_in_list("status", IMPORT_STATUSES), name="status"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        Index("ix_statement_imports_user_created", "user_id", text("created_at DESC")),
        # The 24-hour expiry looks at unconfirmed previews only.
        Index(
            "ix_statement_imports_expiry",
            "expires_at",
            postgresql_where=text("status = 'previewing'"),
        ),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA_LEDGER}.accounts.id"))
    file_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(16), default="previewing")
    # An import's rows are in the account's currency.
    currency: Mapped[str] = mapped_column(String(3))
    header_cells: Mapped[list[str]] = mapped_column(JSONB)
    header_signature: Mapped[str] = mapped_column(String(64))
    # The ColumnMap in use, as JSON; the saved StatementLayout is the per-account memory.
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB)
    layout_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class ImportRow(Base):
    """One row of a preview. Deleted with its import, so an expired preview leaves nothing."""

    __tablename__ = "statement_import_rows"
    __table_args__ = (
        CheckConstraint(_in_list("status", ROW_STATUSES), name="status"),
        CheckConstraint(
            f"category_source IS NULL OR {_in_list('category_source', CATEGORY_SOURCES)}",
            name="category_source",
        ),
        CheckConstraint("direction IS NULL OR direction IN ('out', 'in')", name="direction"),
        Index("ix_statement_import_rows_import_position", "import_id", "position"),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    import_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.statement_imports.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    position: Mapped[int] = mapped_column(Integer)
    # The row's cells as text, so a changed layout can re-read it without the file.
    raw_cells: Mapped[list[str]] = mapped_column(JSONB)
    occurred_on: Mapped[date | None] = mapped_column(Date)
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    direction: Mapped[str | None] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(String(500))
    merchant: Mapped[str | None] = mapped_column(String(200))
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.categories.id", ondelete="SET NULL")
    )
    category_source: Mapped[str | None] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(20), default="to_import")
    note: Mapped[str | None] = mapped_column(String(200))
    is_selected: Mapped[bool] = mapped_column(Boolean, default=False)
    fingerprint: Mapped[str | None] = mapped_column(String(128))
