"""The accounts table."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import (
    SCHEMA_IDENTITY,
    SCHEMA_LEDGER,
    Base,
    created_at_column,
    updated_at_column,
    uuid_pk,
)

ACCOUNT_KINDS = ("bank", "credit_card", "wallet", "cash", "other")


class Account(Base):
    """A place where the user's money is held. Never deleted: retired accounts are archived."""

    __tablename__ = "accounts"
    __table_args__ = (
        CheckConstraint(
            f"kind IN ({', '.join(repr(kind) for kind in ACCOUNT_KINDS)})", name="kind"
        ),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        # Active names are unique per user, ignoring case. Archived accounts keep their names,
        # so a retired "HDFC" does not block a new one.
        Index(
            "uq_accounts_user_active_name",
            "user_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("NOT is_archived"),
        ),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(60))
    kind: Mapped[str] = mapped_column(String(16))
    currency: Mapped[str] = mapped_column(String(3))
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
