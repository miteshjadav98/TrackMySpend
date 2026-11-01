"""The friends and friend_invites tables."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from finance_core.database.base import (
    SCHEMA_IDENTITY,
    SCHEMA_LEDGER,
    Base,
    created_at_column,
    updated_at_column,
    uuid_pk,
)

INVITE_STATUSES = ("pending", "accepted", "declined", "cancelled")
ACTIVE_EMAIL_INDEX = "uq_friends_user_active_email"
PENDING_INVITE_INDEX = "uq_friend_invites_one_pending_per_friend"


class Friend(Base):
    """One person in one user's friends list. Each user has their own row for a friend, so
    two linked users each hold a row for the other."""

    __tablename__ = "friends"
    __table_args__ = (
        # One active friend per email per user. Names may repeat: two Jaymins differ by email.
        Index(
            ACTIVE_EMAIL_INDEX,
            "user_id",
            "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL AND NOT is_archived"),
        ),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str | None] = mapped_column(String(320))  # stored trimmed and lower-cased
    # Set on both sides when an invite is accepted; null for a friend without a login.
    linked_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="SET NULL")
    )
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class FriendInvite(Base):
    """An offer to link two users, sent from one user's friend row to an email address.

    It is matched to the invited user by email, so it works the same whether they already
    have an account or sign up later.
    """

    __tablename__ = "friend_invites"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(status) for status in INVITE_STATUSES)})", name="status"
        ),
        Index(
            PENDING_INVITE_INDEX,
            "friend_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_friend_invites_invitee_email", "invitee_email"),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    friend_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.friends.id", ondelete="CASCADE")
    )
    invitee_email: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = created_at_column()
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
