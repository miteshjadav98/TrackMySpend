"""Transactions: the destination account of a transfer, and the rules that go with it.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, so every existing transaction stays valid as "no destination account".
    op.add_column(
        "transactions", sa.Column("to_account_id", sa.Uuid(), nullable=True), schema="ledger"
    )
    op.create_foreign_key(
        op.f("fk_transactions_to_account_id_accounts"),
        "transactions",
        "accounts",
        ["to_account_id"],
        ["id"],
        source_schema="ledger",
        referent_schema="ledger",
    )
    op.create_index(
        "ix_transactions_user_to_account",
        "transactions",
        ["user_id", "to_account_id"],
        unique=False,
        schema="ledger",
        postgresql_where=sa.text("to_account_id IS NOT NULL"),
    )
    # Only a transfer has a destination; a transfer has both ends, different, and no category.
    # Existing rows are expense or income without a destination, so both checks hold for them.
    op.create_check_constraint(
        op.f("ck_transactions_to_account_only_on_transfer"),
        "transactions",
        "type = 'transfer' OR to_account_id IS NULL",
        schema="ledger",
    )
    op.create_check_constraint(
        op.f("ck_transactions_transfer_shape"),
        "transactions",
        "type <> 'transfer' OR (account_id IS NOT NULL AND to_account_id IS NOT NULL "
        "AND account_id <> to_account_id AND category_id IS NULL)",
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_transactions_transfer_shape"), "transactions", schema="ledger", type_="check"
    )
    op.drop_constraint(
        op.f("ck_transactions_to_account_only_on_transfer"),
        "transactions",
        schema="ledger",
        type_="check",
    )
    op.drop_index("ix_transactions_user_to_account", table_name="transactions", schema="ledger")
    op.drop_constraint(
        op.f("fk_transactions_to_account_id_accounts"),
        "transactions",
        schema="ledger",
        type_="foreignkey",
    )
    op.drop_column("transactions", "to_account_id", schema="ledger")
