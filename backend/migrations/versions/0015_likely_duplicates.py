"""Link likely duplicate preview rows to their matched transactions.

Revision ID: 0015
Revises: 0014
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "statement_import_rows", sa.Column("matched_transaction_id", sa.Uuid()), schema="ledger"
    )
    op.create_foreign_key(
        op.f("fk_statement_import_rows_matched_transaction_id_transactions"),
        "statement_import_rows",
        "transactions",
        ["matched_transaction_id"],
        ["id"],
        source_schema="ledger",
        referent_schema="ledger",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_statement_import_rows_matched_transaction_id",
        "statement_import_rows",
        ["matched_transaction_id"],
        schema="ledger",
        postgresql_where=sa.text("matched_transaction_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_column("statement_import_rows", "matched_transaction_id", schema="ledger")
