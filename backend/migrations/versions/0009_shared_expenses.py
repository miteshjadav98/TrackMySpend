"""Shared expenses, their shares, and the link from a transaction to its shared expense.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamp(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "shared_expenses",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("recorder_id", sa.Uuid(), nullable=False),
        sa.Column("payer_friend_id", sa.Uuid(), nullable=True),
        sa.Column("total_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("merchant", sa.String(length=200), nullable=True),
        _timestamp("created_at"),
        _timestamp("updated_at"),
        sa.CheckConstraint(
            "total_minor > 0 AND total_minor <= 1000000000000000",
            name=op.f("ck_shared_expenses_total"),
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_shared_expenses_currency")),
        sa.ForeignKeyConstraint(
            ["recorder_id"],
            ["identity.users.id"],
            name=op.f("fk_shared_expenses_recorder_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["payer_friend_id"],
            ["ledger.friends.id"],
            name=op.f("fk_shared_expenses_payer_friend_id_friends"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shared_expenses")),
        schema="ledger",
    )
    op.create_index(
        "ix_shared_expenses_recorder_date",
        "shared_expenses",
        ["recorder_id", sa.literal_column("occurred_on DESC"), sa.literal_column("id DESC")],
        schema="ledger",
    )
    op.create_table(
        "shared_expense_shares",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("shared_expense_id", sa.Uuid(), nullable=False),
        sa.Column("friend_id", sa.Uuid(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("amount_minor > 0", name=op.f("ck_shared_expense_shares_amount")),
        sa.ForeignKeyConstraint(
            ["shared_expense_id"],
            ["ledger.shared_expenses.id"],
            name=op.f("fk_shared_expense_shares_shared_expense_id_shared_expenses"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["friend_id"],
            ["ledger.friends.id"],
            name=op.f("fk_shared_expense_shares_friend_id_friends"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_shared_expense_shares")),
        schema="ledger",
    )
    op.create_index(
        "uq_shared_expense_shares_friend",
        "shared_expense_shares",
        ["shared_expense_id", "friend_id"],
        unique=True,
        schema="ledger",
        postgresql_where=sa.text("friend_id IS NOT NULL"),
    )
    op.create_index(
        "uq_shared_expense_shares_recorder",
        "shared_expense_shares",
        ["shared_expense_id"],
        unique=True,
        schema="ledger",
        postgresql_where=sa.text("friend_id IS NULL"),
    )
    op.create_index(
        "ix_shared_expense_shares_friend", "shared_expense_shares", ["friend_id"], schema="ledger"
    )
    op.add_column(
        "transactions",
        sa.Column("shared_expense_id", sa.Uuid(), nullable=True),
        schema="ledger",
    )
    op.create_foreign_key(
        op.f("fk_transactions_shared_expense_id_shared_expenses"),
        "transactions",
        "shared_expenses",
        ["shared_expense_id"],
        ["id"],
        source_schema="ledger",
        referent_schema="ledger",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_transactions_shared_expense",
        "transactions",
        ["shared_expense_id"],
        schema="ledger",
        postgresql_where=sa.text("shared_expense_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_shared_expense", table_name="transactions", schema="ledger")
    op.drop_constraint(
        op.f("fk_transactions_shared_expense_id_shared_expenses"),
        "transactions",
        schema="ledger",
        type_="foreignkey",
    )
    op.drop_column("transactions", "shared_expense_id", schema="ledger")
    op.drop_table("shared_expense_shares", schema="ledger")
    op.drop_table("shared_expenses", schema="ledger")
