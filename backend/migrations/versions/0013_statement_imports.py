"""Statement imports: imports, their preview rows, and remembered statement layouts.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "statement_layouts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("header_signature", sa.String(length=64), nullable=False),
        sa.Column("date_column", sa.Integer(), nullable=False),
        sa.Column("description_column", sa.Integer(), nullable=True),
        sa.Column("amount_column", sa.Integer(), nullable=True),
        sa.Column("debit_column", sa.Integer(), nullable=True),
        sa.Column("credit_column", sa.Integer(), nullable=True),
        sa.Column("reference_column", sa.Integer(), nullable=True),
        sa.Column("date_order", sa.String(length=16), nullable=False),
        sa.Column("sheet_name", sa.String(length=100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in_list("date_order", ("day_first", "month_first")),
            name=op.f("ck_statement_layouts_date_order"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name=op.f("fk_statement_layouts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["ledger.accounts.id"],
            name=op.f("fk_statement_layouts_account_id_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statement_layouts")),
        sa.UniqueConstraint("account_id", name="uq_statement_layouts_account"),
        schema="ledger",
    )

    op.create_table(
        "statement_imports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("header_cells", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("header_signature", sa.String(length=64), nullable=False),
        sa.Column("layout", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("layout_confirmed", sa.Boolean(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("imported_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            _in_list("status", ("previewing", "imported", "undone")),
            name=op.f("ck_statement_imports_status"),
        ),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_statement_imports_currency")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name=op.f("fk_statement_imports_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["ledger.accounts.id"],
            name=op.f("fk_statement_imports_account_id_accounts"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statement_imports")),
        schema="ledger",
    )
    op.create_index(
        "ix_statement_imports_user_created",
        "statement_imports",
        ["user_id", sa.literal_column("created_at DESC")],
        schema="ledger",
    )
    op.create_index(
        "ix_statement_imports_expiry",
        "statement_imports",
        ["expires_at"],
        schema="ledger",
        postgresql_where=sa.text("status = 'previewing'"),
    )

    op.create_table(
        "statement_import_rows",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("import_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("raw_cells", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("direction", sa.String(length=3), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("merchant", sa.String(length=200), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("category_source", sa.String(length=16), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("is_selected", sa.Boolean(), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=True),
        sa.CheckConstraint(
            _in_list("status", ("to_import", "skipped", "likely_duplicate", "transfer")),
            name=op.f("ck_statement_import_rows_status"),
        ),
        sa.CheckConstraint(
            "category_source IS NULL OR "
            + _in_list("category_source", ("rule", "ai", "keyword", "default", "user")),
            name=op.f("ck_statement_import_rows_category_source"),
        ),
        sa.CheckConstraint(
            "direction IS NULL OR direction IN ('out', 'in')",
            name=op.f("ck_statement_import_rows_direction"),
        ),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["ledger.statement_imports.id"],
            name=op.f("fk_statement_import_rows_import_id_statement_imports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name=op.f("fk_statement_import_rows_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["ledger.categories.id"],
            name=op.f("fk_statement_import_rows_category_id_categories"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_statement_import_rows")),
        schema="ledger",
    )
    op.create_index(
        "ix_statement_import_rows_import_position",
        "statement_import_rows",
        ["import_id", "position"],
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_table("statement_import_rows", schema="ledger")
    op.drop_table("statement_imports", schema="ledger")
    op.drop_table("statement_layouts", schema="ledger")
