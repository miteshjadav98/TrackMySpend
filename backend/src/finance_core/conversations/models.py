from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import (
    SCHEMA_CHAT,
    SCHEMA_IDENTITY,
    Base,
    created_at_column,
    updated_at_column,
    uuid_pk,
)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="status"),
        Index("ix_conversations_user_recent", "user_id", text("last_message_at DESC")),
        {"schema": SCHEMA_CHAT},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    title: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()
    last_message_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Message(Base):
    """Chat transcript. This table, not the workflow checkpoint, is the source of truth
    for history; the agent receives a bounded window of it each turn."""

    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
        CheckConstraint("status IN ('completed', 'failed')", name="status"),
        # Idempotency for user messages: a retried send never runs the turn twice.
        Index(
            "uq_messages_conversation_client_id",
            "conversation_id",
            "client_message_id",
            unique=True,
        ),
        Index("ix_messages_conversation_created", "conversation_id", "created_at", "id"),
        Index("ix_messages_reply_to", "reply_to_id"),
        {"schema": SCHEMA_CHAT},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_CHAT}.conversations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    # Typed UI payloads rendered by approved frontend components (never raw HTML/JS).
    ui: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Structured metadata: interaction responses, intent, LLM source.
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    client_message_id: Mapped[uuid.UUID | None] = mapped_column()
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_CHAT}.messages.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(16), default="completed")
    created_at: Mapped[datetime] = created_at_column()
