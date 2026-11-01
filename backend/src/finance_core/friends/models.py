"""The friends, friend_invites, shared_expenses, shared_expense_shares and settlements tables."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
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


class SharedExpense(Base):
    """One bill split among the recorder and some of their friends.

    It holds the whole bill (total, payer, every share). Only the recorder's share is a
    transaction in the recorder's records, so summaries count the share, not the total.
    Deleting one is a hard delete; the audit log keeps what it was.
    """

    __tablename__ = "shared_expenses"
    __table_args__ = (
        CheckConstraint("total_minor > 0 AND total_minor <= 1000000000000000", name="total"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        Index(
            "ix_shared_expenses_recorder_date",
            "recorder_id",
            text("occurred_on DESC"),
            text("id DESC"),
        ),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    recorder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    # The recorder's friend who paid; null means the recorder paid. NO ACTION, like accounts:
    # a friend in a shared expense is archived, never hard-deleted.
    payer_friend_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.friends.id")
    )
    total_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    occurred_on: Mapped[date] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(500))
    merchant: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()


class SharedExpenseShare(Base):
    """What one participant owes of a shared expense, in minor units."""

    __tablename__ = "shared_expense_shares"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount"),
        # One share per person. Two indexes because a null friend (the recorder) never
        # collides in a plain unique index.
        Index(
            "uq_shared_expense_shares_friend",
            "shared_expense_id",
            "friend_id",
            unique=True,
            postgresql_where=text("friend_id IS NOT NULL"),
        ),
        Index(
            "uq_shared_expense_shares_recorder",
            "shared_expense_id",
            unique=True,
            postgresql_where=text("friend_id IS NULL"),
        ),
        Index("ix_shared_expense_shares_friend", "friend_id"),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    shared_expense_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.shared_expenses.id", ondelete="CASCADE")
    )
    # The recorder's friend, or null for the recorder's own share.
    friend_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey(f"{SCHEMA_LEDGER}.friends.id"))
    amount_minor: Mapped[int] = mapped_column(BigInteger)


class Settlement(Base):
    """Money handed over between the recorder and one of their friends to settle up.

    It is not a transaction, so it never counts as spending or income; it only moves the
    balance between the two. `paid_by_recorder` says which way the money went. Each user's own
    account tag sits on their side, so a linked friend can later tag the same settlement
    with their account without touching the recorder's.
    """

    __tablename__ = "settlements"
    __table_args__ = (
        CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000000", name="amount"),
        CheckConstraint("currency ~ '^[A-Z]{3}$'", name="currency"),
        Index("ix_settlements_recorder_date", "recorder_id", text("occurred_on DESC")),
        Index("ix_settlements_friend", "friend_id"),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    recorder_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    # The recorder's friend row. NO ACTION: a friend with a settlement is archived, not deleted.
    friend_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA_LEDGER}.friends.id"))
    paid_by_recorder: Mapped[bool] = mapped_column(Boolean)
    amount_minor: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str] = mapped_column(String(3))
    occurred_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(String(500))
    # Each user's own account tag; the friend's is set from the friend's side.
    recorder_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.accounts.id")
    )
    friend_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.accounts.id")
    )
    created_at: Mapped[datetime] = created_at_column()


NOTICE_KINDS = (
    "shared_expense_added",
    "shared_expense_changed",
    "shared_expense_deleted",
    "settlement_recorded",
    "settlement_deleted",
    "invite_accepted",
    "invite_received",
)


class Notice(Base):
    """Something that happened in a friend's records that the user should hear about.

    It keeps the facts, not the sentence; the sentence is worded when it is read. The shared
    expense is not linked by a foreign key because a deleted one must still have its notice.
    """

    __tablename__ = "notices"
    __table_args__ = (
        CheckConstraint(f"kind IN ({', '.join(repr(kind) for kind in NOTICE_KINDS)})", name="kind"),
        Index("ix_notices_user_created", "user_id", text("created_at DESC"), text("id DESC")),
        Index("ix_notices_user_unread", "user_id", postgresql_where=text("read_at IS NULL")),
        {"schema": SCHEMA_LEDGER},
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(f"{SCHEMA_IDENTITY}.users.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(32))
    # Who did it, named the way this user knows them, kept as written at the time.
    actor_name: Mapped[str] = mapped_column(String(80))
    # This user's own friend row for the actor, so a click can open that friend.
    friend_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(f"{SCHEMA_LEDGER}.friends.id", ondelete="SET NULL")
    )
    subject: Mapped[str | None] = mapped_column(String(500))  # the expense's description
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(String(3))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created_at_column()
