"""Initial schema: identity, ledger, chat, audit (+ agent schema for checkpoints).

Revision ID: 0001
Revises:
Create Date: 2026-10-24
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMAS = ("identity", "ledger", "chat", "audit", "agent")

# Frozen copy of the system categories at the time of this migration. Later additions go
# in new migrations; never edit this list. IDs are deterministic so every environment
# (dev, test, prod) shares them.
_CATEGORY_NAMESPACE = uuid.UUID("0f3c5d1e-8b7a-4c2d-9e6f-1a2b3c4d5e6f")
_SYSTEM_CATEGORIES = [
    ("food", "Food & Dining", "expense", "utensils", 10),
    ("groceries", "Groceries", "expense", "shopping-basket", 20),
    ("transport", "Transport", "expense", "car", 30),
    ("shopping", "Shopping", "expense", "shopping-bag", 40),
    ("housing", "Rent & Housing", "expense", "home", 50),
    ("utilities", "Bills & Utilities", "expense", "receipt", 60),
    ("subscriptions", "Subscriptions", "expense", "repeat", 70),
    ("entertainment", "Entertainment", "expense", "clapperboard", 80),
    ("health", "Health & Fitness", "expense", "heart-pulse", 90),
    ("education", "Education", "expense", "graduation-cap", 100),
    ("travel", "Travel", "expense", "plane", 110),
    ("personal_care", "Personal Care", "expense", "sparkles", 120),
    ("gifts", "Gifts & Donations", "expense", "gift", 130),
    ("insurance", "Insurance", "expense", "shield", 140),
    ("loans", "Loans & EMI", "expense", "landmark", 150),
    ("other", "Other", "expense", "circle-ellipsis", 990),
    ("salary", "Salary", "income", "briefcase", 10),
    ("business", "Business & Freelance", "income", "laptop", 20),
    ("investment_income", "Interest & Dividends", "income", "trending-up", 30),
    ("refund", "Refunds & Cashback", "income", "undo-2", 40),
    ("rental_income", "Rental Income", "income", "key", 50),
    ("gifts_received", "Gifts Received", "income", "gift", 60),
    ("other_income", "Other Income", "income", "circle-plus", 990),
]


def system_category_id(slug: str) -> uuid.UUID:
    return uuid.uuid5(_CATEGORY_NAMESPACE, f"system-category:{slug}")


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')

    # --- identity ---------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("display_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("status IN ('active', 'disabled')", name=op.f("ck_users_status")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        schema="identity",
    )
    op.create_index("uq_users_email", "users", ["email"], unique=True, schema="identity")

    op.create_table(
        "financial_profiles",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("base_currency", sa.String(length=3), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_financial_profiles_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_financial_profiles")),
        schema="identity",
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_auth_sessions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        schema="identity",
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False, schema="identity")
    op.create_index("uq_auth_sessions_token_hash", "auth_sessions", ["token_hash"], unique=True, schema="identity")

    # --- ledger -------------------------------------------------------------------------
    categories = op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=48), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("icon", sa.String(length=32), nullable=True),
        sa.Column("sort_order", sa.SmallInteger(), nullable=False),
        sa.Column("is_archived", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("kind IN ('expense', 'income')", name=op.f("ck_categories_kind")),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_categories_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
        schema="ledger",
    )
    op.create_index("uq_categories_system_slug", "categories", ["slug"], unique=True, schema="ledger", postgresql_where=sa.text("user_id IS NULL"))
    op.create_index("uq_categories_user_slug", "categories", ["user_id", "slug"], unique=True, schema="ledger", postgresql_where=sa.text("user_id IS NOT NULL"))

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("merchant", sa.String(length=200), nullable=True),
        sa.Column("payment_method", sa.String(length=32), nullable=True),
        sa.Column("notes", sa.String(length=1000), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_transactions_currency")),
        sa.CheckConstraint(
            "payment_method IS NULL OR payment_method IN ('cash', 'upi', 'debit_card', 'credit_card', "
            "'card', 'net_banking', 'wallet', 'bank_transfer', 'cheque', 'other')",
            name=op.f("ck_transactions_payment_method"),
        ),
        sa.CheckConstraint("source IN ('chat', 'manual', 'import', 'api')", name=op.f("ck_transactions_source")),
        sa.CheckConstraint("type IN ('expense', 'income', 'transfer')", name=op.f("ck_transactions_type")),
        sa.CheckConstraint("amount_minor > 0 AND amount_minor <= 1000000000000000", name=op.f("ck_transactions_amount")),
        sa.ForeignKeyConstraint(["category_id"], ["ledger.categories.id"], name=op.f("fk_transactions_category_id_categories"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_transactions_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
        schema="ledger",
    )
    op.create_index(
        "ix_transactions_user_live_date", "transactions",
        ["user_id", sa.literal_column("occurred_on DESC"), sa.literal_column("id DESC")],
        unique=False, schema="ledger", postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_transactions_user_source_ref", "transactions", ["user_id", "source_ref"],
        unique=False, schema="ledger", postgresql_where=sa.text("source_ref IS NOT NULL"),
    )
    op.create_index("uq_transactions_user_idempotency", "transactions", ["user_id", "idempotency_key"], unique=True, schema="ledger")

    # --- chat ---------------------------------------------------------------------------
    op.create_table(
        "conversations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.Column("last_message_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name=op.f("ck_conversations_status")),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_conversations_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        schema="chat",
    )
    op.create_index("ix_conversations_user_recent", "conversations", ["user_id", sa.literal_column("last_message_at DESC")], unique=False, schema="chat")

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("ui", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("client_message_id", sa.Uuid(), nullable=True),
        sa.Column("reply_to_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("role IN ('user', 'assistant')", name=op.f("ck_messages_role")),
        sa.CheckConstraint("status IN ('completed', 'failed')", name=op.f("ck_messages_status")),
        sa.ForeignKeyConstraint(["conversation_id"], ["chat.conversations.id"], name=op.f("fk_messages_conversation_id_conversations"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reply_to_id"], ["chat.messages.id"], name=op.f("fk_messages_reply_to_id_messages"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_messages_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        schema="chat",
    )
    op.create_index("ix_messages_conversation_created", "messages", ["conversation_id", "created_at", "id"], unique=False, schema="chat")
    op.create_index("ix_messages_reply_to", "messages", ["reply_to_id"], unique=False, schema="chat")
    op.create_index("uq_messages_conversation_client_id", "messages", ["conversation_id", "client_message_id"], unique=True, schema="chat")

    # --- audit --------------------------------------------------------------------------
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("actor", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("actor IN ('user', 'assistant', 'system')", name=op.f("ck_audit_events_actor")),
        sa.ForeignKeyConstraint(["user_id"], ["identity.users.id"], name=op.f("fk_audit_events_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
        schema="audit",
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"], unique=False, schema="audit")
    op.create_index("ix_audit_events_user_created", "audit_events", ["user_id", sa.literal_column("created_at DESC")], unique=False, schema="audit")

    # --- reference data -----------------------------------------------------------------
    op.bulk_insert(
        categories,
        [
            {
                "id": system_category_id(slug),
                "user_id": None,
                "slug": slug,
                "name": name,
                "kind": kind,
                "icon": icon,
                "sort_order": sort_order,
                "is_archived": False,
            }
            for slug, name, kind, icon, sort_order in _SYSTEM_CATEGORIES
        ],
    )


def downgrade() -> None:
    op.drop_table("audit_events", schema="audit")
    op.drop_table("messages", schema="chat")
    op.drop_table("conversations", schema="chat")
    op.drop_table("transactions", schema="ledger")
    op.drop_table("categories", schema="ledger")
    op.drop_table("auth_sessions", schema="identity")
    op.drop_table("financial_profiles", schema="identity")
    op.drop_table("users", schema="identity")
    # The agent schema holds LangGraph's own tables; leave it alone on downgrade.
    for schema in ("audit", "chat", "ledger", "identity"):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
