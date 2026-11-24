"""Version import previews so a stale view cannot confirm different rows.

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
        "statement_imports",
        sa.Column("preview_revision", sa.Integer(), server_default=sa.text("0"), nullable=False),
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_column("statement_imports", "preview_revision", schema="ledger")
