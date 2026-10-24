"""Declarative base, naming conventions, and schema ownership.

Each bounded context owns a Postgres schema. Financial records, chat history, audit trail,
and agent checkpoints are physically separate, which keeps ownership obvious, allows
per-schema grants later (e.g. a read-only role for analytics), and makes retention
policies easy to apply per area.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from finance_core.ids import uuid7

SCHEMA_IDENTITY = "identity"  # users, sessions, profile/preferences
SCHEMA_LEDGER = "ledger"  # categories, transactions (financial source of truth)
SCHEMA_CHAT = "chat"  # conversations, messages (transcript)
SCHEMA_AUDIT = "audit"  # append-only audit trail
SCHEMA_AGENT = "agent"  # LangGraph checkpoints (created by the checkpointer itself)

APP_SCHEMAS = (SCHEMA_IDENTITY, SCHEMA_LEDGER, SCHEMA_CHAT, SCHEMA_AUDIT)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid7)


def created_at_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_at_column() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
