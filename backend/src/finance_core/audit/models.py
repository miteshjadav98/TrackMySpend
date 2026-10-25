from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import (
    SCHEMA_AUDIT,
    SCHEMA_IDENTITY,
    Base,
    created_at_column,
    uuid_pk,
)


class AuditEvent(Base):
    """Append-only record of consequential changes: who, what, when, from where."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor IN ('user', 'assistant', 'system')", name="actor"),
        Index("ix_audit_events_user_created", "user_id", text("created_at DESC")),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        {"schema": SCHEMA_AUDIT},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    actor: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID | None] = mapped_column()
    request_id: Mapped[str | None] = mapped_column(String(64))
    # Field-level before/after values. Never secrets or raw documents.
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = created_at_column()
