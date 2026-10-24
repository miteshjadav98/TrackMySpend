from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, SmallInteger, String, text
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import (
    SCHEMA_IDENTITY,
    SCHEMA_LEDGER,
    Base,
    created_at_column,
    uuid_pk,
)


class Category(Base):
    """System categories have `user_id IS NULL`; users can add their own."""

    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint("kind IN ('expense', 'income')", name="kind"),
        Index(
            "uq_categories_system_slug",
            "slug",
            unique=True,
            postgresql_where=text("user_id IS NULL"),
        ),
        Index(
            "uq_categories_user_slug",
            "user_id",
            "slug",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    slug: Mapped[str] = mapped_column(String(48))
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(8))
    icon: Mapped[str | None] = mapped_column(String(32))
    sort_order: Mapped[int] = mapped_column(SmallInteger, default=100)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_column()
