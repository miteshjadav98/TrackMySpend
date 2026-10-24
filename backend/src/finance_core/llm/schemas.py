"""Structured-output schemas the model must fill.

The model *reads*; it never decides what gets stored. Every field here is re-validated by
deterministic code (amount grounding, category allowlist, date rules) before anything is
saved. Amounts are strings on purpose: JSON numbers would round-trip through floats.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from finance_core.dates import PeriodKind

Intent = Literal[
    "record_transactions",
    "spending_summary",
    "search_transactions",
    "help",
    "smalltalk",
    "out_of_scope",
]

PaymentMethodLiteral = Literal[
    "cash", "upi", "debit_card", "credit_card", "card", "net_banking",
    "wallet", "bank_transfer", "cheque", "other",
]  # fmt: skip


class _Lenient(BaseModel):
    model_config = ConfigDict(extra="ignore")


class ExtractedTransaction(_Lenient):
    type: Literal["expense", "income"] | None = Field(
        default=None, description="expense = money out, income = money in; null if unclear"
    )
    amount: str | None = Field(
        default=None,
        description="Plain number string as stated by the user, e.g. '350' or '1200.50'; "
        "expand shorthand ('1.5k' -> '1500', '2 lakh' -> '200000'); null if not stated",
    )
    currency: str | None = Field(
        default=None, description="ISO 4217 code only if the user wrote a currency; else null"
    )
    category: str | None = Field(
        default=None, description="One slug from the provided category list, or null"
    )
    date_text: str | None = Field(
        default=None, description="The user's own words for the date, verbatim; null if none"
    )
    date: str | None = Field(
        default=None, description="That date as YYYY-MM-DD relative to today; null if none"
    )
    description: str | None = Field(default=None, description="Short label, 1-5 words")
    merchant: str | None = Field(default=None, description="Business or person, if named")
    payment_method: PaymentMethodLiteral | None = None


class PeriodSpec(_Lenient):
    kind: PeriodKind = "this_month"
    month: str | None = Field(default=None, description="YYYY-MM when kind is 'month'")
    start: str | None = Field(default=None, description="YYYY-MM-DD when kind is 'range'")
    end: str | None = Field(default=None, description="YYYY-MM-DD when kind is 'range'")
    days: int | None = Field(default=None, description="N when kind is 'last_n_days'")


class SearchSpec(_Lenient):
    type: Literal["expense", "income"] | None = None
    category: str | None = Field(default=None, description="Category slug filter, if any")
    text: str | None = Field(default=None, description="Merchant or keyword to match, if any")
    sort: Literal["recent", "largest"] = "recent"
    limit: int | None = Field(default=None, description="How many to show, if the user said")


class PendingAnswer(_Lenient):
    answers_question: bool
    value: str | None = None


class TurnUnderstanding(_Lenient):
    intent: Intent
    transactions: list[ExtractedTransaction] = Field(default_factory=list)
    period: PeriodSpec | None = None
    search: SearchSpec | None = None
    pending_answer: PendingAnswer | None = None
