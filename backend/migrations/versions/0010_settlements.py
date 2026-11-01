"""Settlements: money handed over between a user and one of their friends.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recorder_id", sa.Uuid(), nullable=False),
        sa.Column("friend_id", sa.Uuid(), nullable=False),
        sa.Column("paid_by_recorder", sa.Boolean(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("recorder_account_id", sa.Uuid(), nullable=True),
        sa.Column("friend_account_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "amount_minor > 0 AND amount_minor <= 1000000000000000",
            name=op.f("ck_settlements_amount"),
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_settlements_currency")),
        sa.ForeignKeyConstraint(
            ["recorder_id"],
            ["identity.users.id"],
            name=op.f("fk_settlements_recorder_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["friend_id"], ["ledger.friends.id"], name=op.f("fk_settlements_friend_id_friends")
        ),
        sa.ForeignKeyConstraint(
            ["recorder_account_id"],
            ["ledger.accounts.id"],
            name=op.f("fk_settlements_recorder_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["friend_account_id"],
            ["ledger.accounts.id"],
            name=op.f("fk_settlements_friend_account_id_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settlements")),
        schema="ledger",
    )
    op.create_index(
        "ix_settlements_recorder_date",
        "settlements",
        ["recorder_id", sa.literal_column("occurred_on DESC")],
        schema="ledger",
    )
    op.create_index("ix_settlements_friend", "settlements", ["friend_id"], schema="ledger")


def downgrade() -> None:
    op.drop_table("settlements", schema="ledger")
