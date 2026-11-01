"""Invite one-time codes and settlement idempotency keys.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "friend_invites", sa.Column("code_hash", sa.LargeBinary(length=32)), schema="ledger"
    )
    op.add_column(
        "friend_invites",
        sa.Column("code_expires_at", sa.DateTime(timezone=True)),
        schema="ledger",
    )
    op.add_column(
        "friend_invites",
        sa.Column("code_wrong_tries", sa.Integer(), server_default="0", nullable=False),
        schema="ledger",
    )
    op.add_column(
        "settlements", sa.Column("idempotency_key", sa.String(length=120)), schema="ledger"
    )
    op.create_index(
        "uq_settlements_recorder_idempotency",
        "settlements",
        ["recorder_id", "idempotency_key"],
        unique=True,
        schema="ledger",
    )


def downgrade() -> None:
    op.drop_index("uq_settlements_recorder_idempotency", "settlements", schema="ledger")
    op.drop_column("settlements", "idempotency_key", schema="ledger")
    op.drop_column("friend_invites", "code_wrong_tries", schema="ledger")
    op.drop_column("friend_invites", "code_expires_at", schema="ledger")
    op.drop_column("friend_invites", "code_hash", schema="ledger")
