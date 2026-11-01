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
    "record_settlement",
    "balance_question",
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


class ExtractedShare(_Lenient):
    person: str = Field(
        description="'me' for the user, else the friend's name exactly as the user said it"
    )
    amount: str = Field(description="What that person had, as a plain number string")


class ExtractedTransaction(_Lenient):
    type: Literal["expense", "income", "transfer"] | None = Field(
        default=None,
        description="expense = money out, income = money in, transfer = money moved between "
        "two of the user's own accounts; null if unclear",
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
    account: str | None = Field(
        default=None,
        description="The user's own account the money left (for income: arrived in), as the "
        "user named it; null if none named",
    )
    to_account: str | None = Field(
        default=None, description="For a transfer only: the account the money went to"
    )
    participants: list[str] = Field(
        default_factory=list,
        description="For a shared expense only: the friends sharing it, as the user named them, "
        "never the user themselves; empty when the expense is not shared",
    )
    payer: str | None = Field(
        default=None,
        description="For a shared expense only: the friend's name if a friend paid the bill; "
        "null when the user paid or did not say",
    )
    split: Literal["equal", "exact"] | None = Field(
        default=None,
        description="For a shared expense only: 'exact' when the user said what each person "
        "had, else 'equal'",
    )
    shares: list[ExtractedShare] = Field(
        default_factory=list,
        description="For an exact split only: what each person had, as the user said it",
    )


class SettlementSpec(_Lenient):
    """Money that changed hands between the user and one friend to clear what is owed."""

    friend: str | None = Field(default=None, description="The friend's name as the user said it")
    direction: Literal["friend_paid_me", "i_paid_friend"] | None = Field(
        default=None, description="Who handed the money to whom"
    )
    amount: str | None = Field(
        default=None, description="Plain number string as stated by the user; null if not stated"
    )
    currency: str | None = Field(
        default=None, description="ISO 4217 code only if the user wrote a currency; else null"
    )
    purpose: str | None = Field(
        default=None,
        description="What the money was for when the user said ('his old phone'); null when "
        "it only pays back what is owed",
    )
    account: str | None = Field(
        default=None, description="The user's own account the money went into or left, as named"
    )
    date_text: str | None = Field(default=None, description="The user's own words for the date")
    date: str | None = Field(default=None, description="That date as YYYY-MM-DD; null if none")


class BalanceSpec(_Lenient):
    friend: str | None = Field(
        default=None, description="The friend asked about; null to ask about every friend"
    )


class PeriodSpec(_Lenient):
    kind: PeriodKind = "this_month"
    month: str | None = Field(default=None, description="YYYY-MM when kind is 'month'")
    start: str | None = Field(default=None, description="YYYY-MM-DD when kind is 'range'")
    end: str | None = Field(default=None, description="YYYY-MM-DD when kind is 'range'")
    days: int | None = Field(default=None, description="N when kind is 'last_n_days'")


class SearchSpec(_Lenient):
    type: Literal["expense", "income", "transfer"] | None = None
    category: str | None = Field(default=None, description="Category slug filter, if any")
    text: str | None = Field(default=None, description="Merchant or keyword to match, if any")
    sort: Literal["recent", "largest"] = "recent"
    limit: int | None = Field(default=None, description="How many to show, if the user said")
    shared: bool = Field(
        default=False, description="True when the user asks only for shared expenses"
    )


class PendingAnswer(_Lenient):
    answers_question: bool
    value: str | None = None


class TurnUnderstanding(_Lenient):
    intent: Intent
    transactions: list[ExtractedTransaction] = Field(default_factory=list)
    period: PeriodSpec | None = None
    search: SearchSpec | None = None
    settlement: SettlementSpec | None = None
    balance: BalanceSpec | None = None
    pending_answer: PendingAnswer | None = None
