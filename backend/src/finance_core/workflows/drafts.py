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
from finance_core.llm.schemas import ExtractedShare, ExtractedTransaction
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
    "amount", "amount_confirm", "currency", "type", "friend", "payer", "split", "category",
    "account", "to_account", "date",
]  # fmt: skip


class DraftPerson(BaseModel):
    """A friend a shared expense is split with, from the name the user said to the friend it means.

    `friend_id` is set once the name matches exactly one of the user's friends. A name matching
    several is `ambiguous`; one matching none stays unresolved until the user agrees to add
    them (`is_new`), and the friend is then created at save.
    """

    model_config = ConfigDict(extra="ignore")

    said: str
    friend_id: str | None = None
    name: str | None = None  # the friend's saved name, or the name to add
    is_new: bool = False
    ambiguous: bool = False
    paid: bool = False  # this friend paid the bill
    amount: str | None = None  # what they had, for an exact split

    def is_resolved(self) -> bool:
        return self.friend_id is not None or self.is_new

    def display_name(self) -> str:
        return self.name or self.said


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
    # A shared expense: the friends it is split with (never the user), how, and the user's own
    # amount when the split is exact. Empty `people` means the expense is not shared.
    people: list[DraftPerson] = []
    split: Literal["equal", "exact"] = "equal"
    my_amount: str | None = None

    def is_shared(self) -> bool:
        return self.type == "expense" and bool(self.people)

    def payer_is_friend(self) -> bool:
        return any(person.paid for person in self.people)

    def exact_amounts_added(self) -> Decimal | None:
        """What the exact amounts add up to, or None while someone's amount is missing."""
        given = [self.my_amount, *(person.amount for person in self.people)]
        if None in given:
            return None
        try:
            return sum((Decimal(a) for a in given if a is not None), Decimal(0))
        except InvalidOperation:
            return None

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

    draft = TransactionDraft(
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
    return draft.model_copy(update=_sharing_fields(extracted))


def _sharing_fields(extracted: ExtractedTransaction) -> dict[str, object]:
    """The draft's shared-expense fields from what the model read; empty if not shared."""
    if extracted.type in ("income", "transfer") or not extracted.participants:
        return {}
    names = [_clean(name, 80) for name in extracted.participants]
    people = _unique_people([name for name in names if name])
    payer = _clean(extracted.payer, 80)
    if payer and payer.casefold() not in {p.said.casefold() for p in people}:
        people.append(DraftPerson(said=payer))  # whoever paid is sharing too
    exact = extracted.split == "exact"
    return {
        "type": "expense",
        "people": [
            p.model_copy(
                update={
                    "paid": bool(payer) and p.said.casefold() == (payer or "").casefold(),
                    "amount": _amount_for(p.said, extracted.shares) if exact else None,
                }
            )
            for p in people
        ],
        "split": "exact" if exact else "equal",
        "my_amount": _amount_for("me", extracted.shares) if exact else None,
    }


def _unique_people(names: list[str]) -> list[DraftPerson]:
    people: list[DraftPerson] = []
    for name in names:
        if name.casefold() not in {p.said.casefold() for p in people}:
            people.append(DraftPerson(said=name))
    return people


def _amount_for(person: str, shares: list[ExtractedShare]) -> str | None:
    """What the user said `person` had, as a plain number string; None if they did not say."""
    for share in shares:
        if share.person.strip().casefold() == person.casefold():
            parsed = normalize_amount(share.amount)
            return format(parsed[0].normalize(), "f") if parsed else None
    return None


@dataclass(frozen=True, slots=True)
class Issue:
    field: IssueField
    reason: str


def first_issue(draft: TransactionDraft, *, base_currency: str, today: date) -> Issue | None:
    """The single most important thing to ask next, or None if the draft is complete.

    Order: amount, then confirming an unverified amount, currency, type (needed to offer
    the right categories), the friends of a shared expense, category, and finally the date. A
    transfer has no category; it asks for the account the money left, then the one it went to,
    before the date.
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
    if draft.is_shared() and (sharing_issue := _sharing_issue(draft)) is not None:
        return sharing_issue
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


def _sharing_issue(draft: TransactionDraft) -> Issue | None:
    """What a shared expense still needs: every friend known, a payer the service accepts, and
    exact amounts that add up to the total."""
    for person in draft.people:
        if not person.is_resolved():
            return Issue("friend", "ambiguous" if person.ambiguous else "unknown")
    if draft.payer_is_friend() and len(draft.people) > 1:
        return Issue("payer", "too_many")  # a friend paid: only that friend can share it
    if draft.split == "exact":
        added = draft.exact_amounts_added()
        if added is None:
            return Issue("split", "missing")
        if added != draft.decimal_amount():
            return Issue("split", "mismatch")
    return None


def merge_repeated_people(people: list[DraftPerson]) -> list[DraftPerson]:
    """Two names that turn out to be the same friend ("Jaymin" and "Jaymin Shah") count once;
    a friend counts as the payer if either name said so."""
    kept: list[DraftPerson] = []
    for person in people:
        twin = next((k for k in kept if person.friend_id and k.friend_id == person.friend_id), None)
        if twin is None:
            kept.append(person)
        elif person.paid and not twin.paid:
            kept[kept.index(twin)] = twin.model_copy(update={"paid": True})
    return kept
