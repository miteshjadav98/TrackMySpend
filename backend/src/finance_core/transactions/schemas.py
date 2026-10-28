from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from finance_core.accounts.schemas import AccountRef
from finance_core.categories.schemas import CategoryRef
from finance_core.schemas import ApiInput, ApiModel

TransactionTypeField = Literal["expense", "income"]
PaymentMethodField = Literal[
    "cash", "upi", "debit_card", "credit_card", "card", "net_banking",
    "wallet", "bank_transfer", "cheque", "other",
]  # fmt: skip
SourceField = Literal["chat", "manual", "import", "api"]
SortField = Literal["recent", "largest"]

PAYMENT_METHOD_LABELS: dict[str, str] = {
    "cash": "Cash", "upi": "UPI", "debit_card": "Debit card", "credit_card": "Credit card",
    "card": "Card", "net_banking": "Net banking", "wallet": "Wallet",
    "bank_transfer": "Bank transfer", "cheque": "Cheque", "other": "Other",
}  # fmt: skip


class TransactionView(ApiModel):
    id: uuid.UUID
    type: TransactionTypeField
    amount: Decimal
    amount_minor: int
    currency: str
    amount_formatted: str
    occurred_on: date
    category: CategoryRef | None
    # Defaults to None so saved chat cards stored before accounts existed still load.
    account: AccountRef | None = None
    description: str | None
    merchant: str | None
    payment_method: PaymentMethodField | None
    notes: str | None
    source: SourceField
    version: int
    created_at: datetime
    updated_at: datetime


class TransactionCreate(ApiInput):
    type: TransactionTypeField
    amount: Decimal = Field(gt=0, max_digits=18)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    occurred_on: date | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    payment_method: PaymentMethodField | None = None
    notes: str | None = Field(default=None, max_length=1000)


class TransactionUpdate(ApiInput):
    """Partial update. Only fields present in the request change; `null` clears a field.

    `version` must match the stored version (optimistic concurrency): a stale edit from
    another tab gets a 409 instead of silently overwriting newer data.
    """

    version: int = Field(ge=1)
    type: TransactionTypeField | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    occurred_on: date | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    payment_method: PaymentMethodField | None = None
    notes: str | None = Field(default=None, max_length=1000)


class TransactionPage(ApiModel):
    items: list[TransactionView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class TransactionQuery:
    type: TransactionTypeField | None = None
    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None
    date_from: date | None = None
    date_to: date | None = None
    text: str | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    currency: str | None = None
    sort: SortField = "recent"
    limit: int = 50
    cursor: str | None = None


@dataclass(frozen=True, slots=True)
class NewTransaction:
    """A fully validated transaction, ready to persist."""

    type: str
    amount_minor: int
    currency: str
    occurred_on: date
    category_id: uuid.UUID | None
    description: str | None
    merchant: str | None
    payment_method: str | None
    notes: str | None = None
    account_id: uuid.UUID | None = None
