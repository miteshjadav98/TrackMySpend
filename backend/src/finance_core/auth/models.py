from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import SCHEMA_IDENTITY, Base, created_at_column, uuid_pk


class AuthSession(Base):
    """Server-side session. The cookie carries a random token; only its SHA-256 is stored,
    so a database leak does not leak usable sessions. Revocation is immediate."""

    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("uq_auth_sessions_token_hash", "token_hash", unique=True),
        Index("ix_auth_sessions_user_id", "user_id"),
        {"schema": SCHEMA_IDENTITY},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32))
    created_at: Mapped[datetime] = created_at_column()
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(256))
    ip_address: Mapped[str | None] = mapped_column(String(45))
