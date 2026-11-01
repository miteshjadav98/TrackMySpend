"""Friends and friend invites.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "friends",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("linked_user_id", sa.Uuid(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name=op.f("fk_friends_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["linked_user_id"],
            ["identity.users.id"],
            name=op.f("fk_friends_linked_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_friends")),
        schema="ledger",
    )
    op.create_index(
        "uq_friends_user_active_email",
        "friends",
        ["user_id", "email"],
        unique=True,
        schema="ledger",
        postgresql_where=sa.text("email IS NOT NULL AND NOT is_archived"),
    )
    op.create_table(
        "friend_invites",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("friend_id", sa.Uuid(), nullable=False),
        sa.Column("invitee_email", sa.String(length=320), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        _timestamp("created_at"),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled')",
            name=op.f("ck_friend_invites_status"),
        ),
        sa.ForeignKeyConstraint(
            ["friend_id"],
            ["ledger.friends.id"],
            name=op.f("fk_friend_invites_friend_id_friends"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_friend_invites")),
        schema="ledger",
    )
    op.create_index(
        "uq_friend_invites_one_pending_per_friend",
        "friend_invites",
        ["friend_id"],
        unique=True,
        schema="ledger",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_friend_invites_invitee_email", "friend_invites", ["invitee_email"], schema="ledger"
    )


def downgrade() -> None:
    op.drop_table("friend_invites", schema="ledger")
    op.drop_table("friends", schema="ledger")
