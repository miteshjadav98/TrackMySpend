from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from finance_core.database.base import (
    SCHEMA_IDENTITY,
    Base,
    created_at_column,
    updated_at_column,
    uuid_pk,
)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
        Index("uq_users_email", "email", unique=True),
        {"schema": SCHEMA_IDENTITY},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Stored normalised (trimmed + lower-cased) so uniqueness is case-insensitive.
    email: Mapped[str] = mapped_column(String(320))
    # Nullable so accounts from an external identity provider can exist without one.
    password_hash: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    profile: Mapped[FinancialProfile] = relationship(
        back_populates="user", lazy="raise", cascade="all, delete-orphan", uselist=False
    )


class FinancialProfile(Base):
    """Long-term, user-controlled preferences that change how input is interpreted."""

    __tablename__ = "financial_profiles"
    __table_args__ = {"schema": SCHEMA_IDENTITY}

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE"), primary_key=True
    )
    base_currency: Mapped[str] = mapped_column(String(3))
    timezone: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    user: Mapped[User] = relationship(back_populates="profile", lazy="raise")
