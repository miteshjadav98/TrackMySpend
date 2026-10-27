"""Transaction drafts: what we have understood so far, and what is still missing.

Everything here is deterministic and side-effect free, so the clarification logic is
unit-tested without a model, a database, or a graph.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict

from finance_core.dates import (
    EARLIEST_ALLOWED_DATE,
    day_first_for_locale,
    parse_iso_date,
    resolve_date_expression,
)
from finance_core.llm.schemas import ExtractedTransaction
from finance_core.money import (
    SUPPORTED_CURRENCIES,
    MoneyError,
    amount_is_grounded,
    normalize_currency,
    parse_amount_with_currency,
    to_minor,
)
from finance_core.workflows.category_choice import CategorySource

IssueField = Literal["amount", "amount_confirm", "currency", "type", "category", "date"]


class TransactionDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    origin_message_id: str
    # The user's message this draft was understood from: a category named in it wins.
    source_text: str = ""
    type: Literal["expense", "income"] | None = None
    amount: str | None = None  # exact decimal string
    amount_confirmed: bool = False  # literally typed by the user, or confirmed by them
    currency: str | None = None  # ISO code as given; None means "use the base currency"
    category_slug: str | None = None  # what the model/parser suggested
    category_id: str | None = None  # resolved against the user's categories
    category_name: str | None = None
    category_source: CategorySource | None = None  # which precedence level chose it
    category_text: str | None = None  # the user's own name for a new category
    category_skipped: bool = False
    date: str | None = None  # ISO date
    date_text: str | None = None
    date_assumed: bool = False  # no date was mentioned, so "today" was used
    description: str | None = None
    merchant: str | None = None
    payment_method: str | None = None

    def decimal_amount(self) -> Decimal | None:
        if self.amount is None:
            return None
        try:
            return Decimal(self.amount)
        except InvalidOperation:
            return None

    def effective_currency(self, base_currency: str) -> str:
        return (self.currency or base_currency).upper()


def _clean(text: str | None, limit: int) -> str | None:
    if not text:
        return None
    text = " ".join(text.split())
    return text[:limit] or None


def normalize_amount(raw: str | None) -> tuple[Decimal, str | None] | None:
    if raw is None:
        return None
    return parse_amount_with_currency(str(raw))


def draft_from_extraction(
    extracted: ExtractedTransaction,
    *,
    draft_id: str,
    origin_message_id: str,
    source_text: str,
    today: date,
    locale: str,
) -> TransactionDraft:
    amount: str | None = None
    grounded = False
    parsed_currency: str | None = None
    if parsed := normalize_amount(extracted.amount):
        value, parsed_currency = parsed
        amount = format(value.normalize(), "f")
        # The model may read amounts but never invent them.
        grounded = amount_is_grounded(value, source_text)

    raw_currency = extracted.currency or parsed_currency
    currency = normalize_currency(raw_currency) if raw_currency else None
    if raw_currency and currency is None:
        currency = raw_currency.strip().upper()[:8]  # unsupported; the workflow will ask

    resolved: date | None = None
    if extracted.date_text:
        # Our own resolver is authoritative; the model's ISO date is only a fallback.
        resolved = resolve_date_expression(
            extracted.date_text, today, day_first=day_first_for_locale(locale)
        )
    if resolved is None:
        resolved = parse_iso_date(extracted.date)
    assumed = resolved is None and not extracted.date_text and not extracted.date
    if assumed:
        resolved = today

    return TransactionDraft(
        id=draft_id,
        origin_message_id=origin_message_id,
        source_text=source_text,
        type=extracted.type,
        amount=amount,
        amount_confirmed=grounded,
        currency=currency,
        category_slug=extracted.category,
        date=resolved.isoformat() if resolved else None,
        date_text=extracted.date_text,
        date_assumed=assumed,
        description=_clean(extracted.description, 120),
        merchant=_clean(extracted.merchant, 120),
        payment_method=extracted.payment_method,
    )


@dataclass(frozen=True, slots=True)
class Issue:
    field: IssueField
    reason: str


def first_issue(draft: TransactionDraft, *, base_currency: str, today: date) -> Issue | None:
    """The single most important thing to ask next, or None if the draft is complete.

    Order: amount, then confirming an unverified amount, currency, type (needed to offer
    the right categories), category, and finally the date.
    """
    value = draft.decimal_amount()
    if value is None or value <= 0:
        return Issue("amount", "missing")
    currency = draft.effective_currency(base_currency)
    if currency not in SUPPORTED_CURRENCIES:
        return Issue("currency", "unsupported")
    try:
        to_minor(value, currency)
    except MoneyError as exc:
        return Issue("amount", "precision" if "decimal" in str(exc) else "invalid")
    if not draft.amount_confirmed:
        return Issue("amount_confirm", "unverified")
    if draft.type is None:
        return Issue("type", "missing")
    if draft.category_id is None and not draft.category_skipped and not draft.category_text:
        return Issue("category", "missing")
    occurred = parse_iso_date(draft.date)
    if occurred is None:
        return Issue("date", "missing")
    if occurred > today:
        return Issue("date", "future")
    if occurred < EARLIEST_ALLOWED_DATE:
        return Issue("date", "too_old")
    return None
