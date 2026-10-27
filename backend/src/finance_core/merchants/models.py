"""The merchant rules table (ledger schema)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import (
    SCHEMA_IDENTITY,
    SCHEMA_LEDGER,
    Base,
    created_at_column,
    updated_at_column,
    uuid_pk,
)


class MerchantRule(Base):
    """The category a user files a merchant under, learned from their saved transactions.

    One row per (user, transaction type, merchant key), so expense and income rules for the
    same merchant stay apart.
    """

    __tablename__ = "merchant_rules"
    __table_args__ = (
        CheckConstraint("type IN ('expense', 'income')", name="type"),
        CheckConstraint("times_used > 0", name="times_used"),
        UniqueConstraint("user_id", "type", "merchant_key"),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    type: Mapped[str] = mapped_column(String(16))
    merchant_key: Mapped[str] = mapped_column(String(200))
    merchant: Mapped[str] = mapped_column(String(200))  # the latest spelling, for display
    # NO ACTION, like every reference to a category: categories are never hard-deleted.
    category_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA_LEDGER}.categories.id"))
    times_used: Mapped[int] = mapped_column(Integer)
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
