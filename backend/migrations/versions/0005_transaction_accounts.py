"""Transactions: the account an expense or income was paid from or into.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, so every existing transaction stays valid as "no account".
    op.add_column(
        "transactions", sa.Column("account_id", sa.Uuid(), nullable=True), schema="ledger"
    )
    op.create_foreign_key(
        op.f("fk_transactions_account_id_accounts"),
        "transactions",
        "accounts",
        ["account_id"],
        ["id"],
        source_schema="ledger",
        referent_schema="ledger",
    )
    op.create_index(
        "ix_transactions_user_account",
        "transactions",
        ["user_id", "account_id"],
        unique=False,
        schema="ledger",
        postgresql_where=sa.text("account_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_user_account", table_name="transactions", schema="ledger")
    op.drop_constraint(
        op.f("fk_transactions_account_id_accounts"),
        "transactions",
        schema="ledger",
        type_="foreignkey",
    )
    op.drop_column("transactions", "account_id", schema="ledger")
