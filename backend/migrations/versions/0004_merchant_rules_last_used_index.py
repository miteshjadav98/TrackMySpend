"""Merchant rules: an index for listing a user's rules most recently used first.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Serves Settings → Merchant rules: newest use first, with keyset pagination.
    op.create_index(
        "ix_merchant_rules_user_last_used",
        "merchant_rules",
        ["user_id", sa.literal_column("last_used_at DESC"), sa.literal_column("id DESC")],
        unique=False,
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_index("ix_merchant_rules_user_last_used", table_name="merchant_rules", schema="ledger")
