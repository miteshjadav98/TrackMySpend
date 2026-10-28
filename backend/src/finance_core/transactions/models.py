from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import (
    SCHEMA_IDENTITY,
    SCHEMA_LEDGER,
    Base,
    created_at_column,
    updated_at_column,
    uuid_pk,
)

TRANSACTION_TYPES = ("expense", "income", "transfer")
PAYMENT_METHODS = (
    "cash", "upi", "debit_card", "credit_card", "card", "net_banking",
    "wallet", "bank_transfer", "cheque", "other",
)  # fmt: skip
TRANSACTION_SOURCES = ("chat", "manual", "import", "api")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Transaction(Base):
    """A financial record: the authoritative source for every total and balance."""

    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(_in_list("type", TRANSACTION_TYPES), name="type"),
        CheckConstraint(
            f"payment_method IS NULL OR {_in_list('payment_method', PAYMENT_METHODS)}",
            name="payment_method",
        ),
        CheckConstraint(_in_list("source", TRANSACTION_SOURCES), name="source"),
        CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000000", name="amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        # Idempotency: one row per (user, key). NULL keys are allowed and never collide.
        Index("uq_transactions_user_idempotency", "user_id", "idempotency_key", unique=True),
        # Only a transfer has a destination; a transfer has both ends, different, and no category.
        CheckConstraint(
            "type = 'transfer' OR to_account_id IS NULL", name="to_account_only_on_transfer"
        ),
        CheckConstraint(
            "type <> 'transfer' OR (account_id IS NOT NULL AND to_account_id IS NOT NULL "
            "AND account_id <> to_account_id AND category_id IS NULL)",
            name="transfer_shape",
        ),
        # Listing, date-range aggregation and keyset pagination for live rows.
        Index(
            "ix_transactions_user_live_date",
            "user_id",
            text("occurred_on DESC"),
            text("id DESC"),
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_transactions_user_source_ref",
            "user_id",
            "source_ref",
            postgresql_where=text("source_ref IS NOT NULL"),
        ),
        # The account filter on the transaction list.
        Index(
            "ix_transactions_user_account",
            "user_id",
            "account_id",
            postgresql_where=text("account_id IS NOT NULL"),
        ),
        # The account filter also matches the destination end of a transfer.
        Index(
            "ix_transactions_user_to_account",
            "user_id",
            "to_account_id",
            postgresql_where=text("to_account_id IS NOT NULL"),
        ),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(16))
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    occurred_on: Mapped[date] = mapped_column(Date)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.categories.id", ondelete="RESTRICT")
    )
    # The account the money was paid from (or, for income, into). NO ACTION, like every
    # reference to an account: accounts are archived, never hard-deleted.
    account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA_LEDGER}.accounts.id"))
    # Where a transfer's money went; NULL for expense and income.
    to_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.accounts.id")
    )
    description: Mapped[str | None] = mapped_column(String(500))
    merchant: Mapped[str | None] = mapped_column(String(200))
    payment_method: Mapped[str | None] = mapped_column(String(32))
    notes: Mapped[str | None] = mapped_column(String(1000))
    source: Mapped[str] = mapped_column(String(16), default="manual")
    # Provenance, e.g. the chat message a transaction was extracted from.
    source_ref: Mapped[str | None] = mapped_column(String(128))
    idempotency_key: Mapped[str | None] = mapped_column(String(128))
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # SQLAlchemy adds "AND version = :old" to every UPDATE, so a concurrent edit fails
    # loudly instead of silently overwriting (optimistic concurrency control).
    __mapper_args__ = {"version_id_col": version}
