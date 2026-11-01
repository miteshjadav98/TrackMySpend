"""Notices: what a linked friend is told after someone else's change.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KINDS = (
    "shared_expense_added",
    "shared_expense_changed",
    "shared_expense_deleted",
    "settlement_recorded",
    "settlement_deleted",
    "invite_accepted",
    "invite_received",
)


def upgrade() -> None:
    op.create_table(
        "notices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("actor_name", sa.String(length=80), nullable=False),
        sa.Column("friend_id", sa.Uuid(), nullable=True),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN (" + ", ".join(repr(kind) for kind in KINDS) + ")",
            name=op.f("ck_notices_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name=op.f("fk_notices_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["friend_id"],
            ["ledger.friends.id"],
            name=op.f("fk_notices_friend_id_friends"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notices")),
        schema="ledger",
    )
    op.create_index(
        "ix_notices_user_created",
        "notices",
        ["user_id", sa.literal_column("created_at DESC"), sa.literal_column("id DESC")],
        schema="ledger",
    )
    op.create_index(
        "ix_notices_user_unread",
        "notices",
        ["user_id"],
        schema="ledger",
        postgresql_where=sa.text("read_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_table("notices", schema="ledger")
