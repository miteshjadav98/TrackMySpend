"""Add optional dated account anchors and loan accounts."""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def _kinds(values: str) -> None:
    op.drop_constraint(op.f("ck_accounts_kind"), "accounts", schema="ledger")
    op.create_check_constraint(
        op.f("ck_accounts_kind"), "accounts", f"kind IN ({values})", schema="ledger"
    )


def upgrade() -> None:
    _kinds("'bank', 'credit_card', 'wallet', 'cash', 'other', 'loan'")
    op.add_column("accounts", sa.Column("anchor_minor", sa.BigInteger()), schema="ledger")
    op.add_column("accounts", sa.Column("anchor_date", sa.Date()), schema="ledger")
    op.create_check_constraint(
        op.f("ck_accounts_anchor_pair"),
        "accounts",
        "(anchor_minor IS NULL) = (anchor_date IS NULL)",
        schema="ledger",
    )


def downgrade() -> None:
    _kinds("'bank', 'credit_card', 'wallet', 'cash', 'other'")
    op.drop_constraint(op.f("ck_accounts_anchor_pair"), "accounts", schema="ledger")
    op.drop_column("accounts", "anchor_date", schema="ledger")
    op.drop_column("accounts", "anchor_minor", schema="ledger")
