"""Merchant rules: the category each user files a merchant under.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "merchant_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("merchant_key", sa.String(length=200), nullable=False),
        sa.Column("merchant", sa.String(length=200), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("times_used", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint("type IN ('expense', 'income')", name=op.f("ck_merchant_rules_type")),
        sa.CheckConstraint("times_used > 0", name=op.f("ck_merchant_rules_times_used")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["identity.users.id"],
            name=op.f("fk_merchant_rules_user_id_users"),
            ondelete="CASCADE",
        ),
        # NO ACTION (the default): categories are never hard-deleted, and a cascading user
        # deletion removes the user's rules and custom categories in the same statement.
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["ledger.categories.id"],
            name=op.f("fk_merchant_rules_category_id_categories"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_merchant_rules")),
        sa.UniqueConstraint(
            "user_id",
            "type",
            "merchant_key",
            name=op.f("uq_merchant_rules_user_id_type_merchant_key"),
        ),
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_table("merchant_rules", schema="ledger")
