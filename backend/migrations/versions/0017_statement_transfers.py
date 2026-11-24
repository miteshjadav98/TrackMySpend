"""Suggest statement transfers and record each confirmed side.

Revision ID: 0017
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "statement_import_rows",
        sa.Column(
            "transfer_account_chosen", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        schema="ledger",
    )
    op.add_column(
        "statement_import_rows", sa.Column("transfer_account_id", sa.Uuid()), schema="ledger"
    )
    op.add_column(
        "statement_import_rows", sa.Column("matched_transfer_id", sa.Uuid()), schema="ledger"
    )
    op.create_foreign_key(
        op.f("fk_statement_import_rows_transfer_account_id_accounts"),
        "statement_import_rows",
        "accounts",
        ["transfer_account_id"],
        ["id"],
        source_schema="ledger",
        referent_schema="ledger",
    )
    op.create_foreign_key(
        op.f("fk_statement_import_rows_matched_transfer_id_transactions"),
        "statement_import_rows",
        "transactions",
        ["matched_transfer_id"],
        ["id"],
        source_schema="ledger",
        referent_schema="ledger",
        ondelete="SET NULL",
    )
    op.create_table(
        "statement_transfer_sides",
        sa.Column("transfer_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("import_row_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.PrimaryKeyConstraint(
            "transfer_id", "account_id", name=op.f("pk_statement_transfer_sides")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["ledger.accounts.id"],
            name=op.f("fk_statement_transfer_sides_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["transfer_id"],
            ["ledger.transactions.id"],
            name=op.f("fk_statement_transfer_sides_transfer_id_transactions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["import_row_id"],
            ["ledger.statement_import_rows.id"],
            name=op.f("fk_statement_transfer_sides_import_row_id_statement_import_rows"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name=op.f("fk_statement_transfer_sides_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("import_row_id", name="uq_statement_transfer_sides_import_row"),
        sa.UniqueConstraint(
            "user_id", "fingerprint", name="uq_statement_transfer_sides_fingerprint"
        ),
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_table("statement_transfer_sides", schema="ledger")
    op.drop_column("statement_import_rows", "matched_transfer_id", schema="ledger")
    op.drop_column("statement_import_rows", "transfer_account_id", schema="ledger")
    op.drop_column("statement_import_rows", "transfer_account_chosen", schema="ledger")
