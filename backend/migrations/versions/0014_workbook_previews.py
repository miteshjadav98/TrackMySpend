"""Track the worksheet selected for a statement preview.

Revision ID: 0014
Revises: 0013
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("statement_imports", sa.Column("sheet_name", sa.String(100)), schema="ledger")
    op.add_column(
        "statement_imports", sa.Column("sheet_names", postgresql.JSONB()), schema="ledger"
    )
    op.add_column("statement_imports", sa.Column("workbook_digest", sa.String(64)), schema="ledger")


def downgrade() -> None:
    op.drop_column("statement_imports", "workbook_digest", schema="ledger")
    op.drop_column("statement_imports", "sheet_names", schema="ledger")
    op.drop_column("statement_imports", "sheet_name", schema="ledger")
