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
from finance_core.llm.rules import item_segment
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

IssueField = Literal[
    "amount", "amount_confirm", "currency", "type", "category", "account", "to_account", "date"
]


class TransactionDraft(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    origin_message_id: str
    # The user's message this draft was understood from: a category named in it wins.
    source_text: str = ""
    # Just this item's part of that message ("swiggy 300" of "swiggy 300 and dinner 400"),
    # so a category named for one item is not credited to another.
    item_text: str = ""
    type: Literal["expense", "income", "transfer"] | None = None
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
    # A transfer's two ends. `account` is the name as the user said it; `account_id` is the
    # account it resolved to, or None with `account_new` set when the user typed a new name
    # in a clarification, which is created at save as `account_name`.
    account: str | None = None
    account_id: str | None = None
    account_name: str | None = None
    account_new: bool = False
    to_account: str | None = None
    to_account_id: str | None = None
    to_account_name: str | None = None
    to_account_new: bool = False

    def has_account(self) -> bool:
        return self.account_id is not None or self.account_new

    def has_to_account(self) -> bool:
        return self.to_account_id is not None or self.to_account_new

    def same_account_both_ends(self) -> bool:
        if self.account_id is not None and self.account_id == self.to_account_id:
            return True
        names = (self.account_name or "").casefold(), (self.to_account_name or "").casefold()
        return (self.account_new or self.to_account_new) and names[0] == names[1] != ""

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
        item_text=item_segment(source_text, Decimal(amount)) if amount else source_text,
        type=extracted.type,
        amount=amount,
        amount_confirmed=grounded,
        currency=currency,
        category_slug=extracted.category,
        date=resolved.isoformat() if resolved else None,
        date_text=extracted.date_text,
        date_assumed=assumed,
        description=_clean(extracted.description, 120),
        merchant=_clean(extracted.merchant, 120) if extracted.type != "transfer" else None,
        payment_method=extracted.payment_method if extracted.type != "transfer" else None,
        account=_clean(extracted.account, 60),
        to_account=_clean(extracted.to_account, 60) if extracted.type == "transfer" else None,
    )


@dataclass(frozen=True, slots=True)
class Issue:
    field: IssueField
    reason: str


def first_issue(draft: TransactionDraft, *, base_currency: str, today: date) -> Issue | None:
    """The single most important thing to ask next, or None if the draft is complete.

    Order: amount, then confirming an unverified amount, currency, type (needed to offer
    the right categories), category, and finally the date. A transfer has no category; it
    asks for the account the money left, then the one it went to, before the date.
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
    if draft.type == "transfer":
        if not draft.has_account():
            return Issue("account", "unknown" if draft.account else "missing")
        if not draft.has_to_account():
            return Issue("to_account", "unknown" if draft.to_account else "missing")
        if draft.same_account_both_ends():
            return Issue("to_account", "same")
    elif draft.category_id is None and not draft.category_skipped and not draft.category_text:
        return Issue("category", "missing")
    occurred = parse_iso_date(draft.date)
    if occurred is None:
        return Issue("date", "missing")
    if occurred > today:
        return Issue("date", "future")
    if occurred < EARLIEST_ALLOWED_DATE:
        return Issue("date", "too_old")
    return None
