"""Reconcile the model's reading with the deterministic parser.

Measured on the evaluation set (tests/evals), the fast model's misses are almost always
*omissions* (category, payment method, or date left empty) and occasionally a duplicated
transaction. The rules engine is high-precision on exactly those keyword signals and
costs microseconds, so:

- the model may not return more transactions with a given amount than the user wrote;
- empty fields are filled from the parser's reading of the same amount.

The model's non-empty values always win; the parser only fills gaps.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal, InvalidOperation

from finance_core.accounts.names import could_mean_an_account, same_account_name
from finance_core.categories.defaults import FALLBACK_SLUG, system_category
from finance_core.dates import day_first_for_locale, resolve_date_expression
from finance_core.llm.rules import extract_search, extract_transactions
from finance_core.llm.schemas import ExtractedTransaction, TurnUnderstanding
from finance_core.money import find_amounts, parse_amount

_FILLABLE = ("amount", "type", "currency", "payment_method", "merchant", "account")


def _value(tx: ExtractedTransaction) -> Decimal | None:
    if tx.amount is None:
        return None
    try:
        return parse_amount(tx.amount) or Decimal(tx.amount)
    except InvalidOperation:
        return None


def _drop_duplicates(
    transactions: list[ExtractedTransaction], text: str
) -> list[ExtractedTransaction]:
    written = Counter(mention.value for mention in find_amounts(text))
    used: Counter[Decimal] = Counter()
    kept: list[ExtractedTransaction] = []
    for tx in transactions:
        value = _value(tx)
        if value is not None and written[value]:
            if used[value] >= written[value]:
                continue  # more copies of this amount than the user wrote
            used[value] += 1
        kept.append(tx)
    return kept


def _complements(base: ExtractedTransaction, part: ExtractedTransaction) -> bool:
    """`part` has no amount and only fills gaps in `base`: one transaction the model split.

    A genuinely separate item conflicts somewhere ("Lunch" vs "Book") and is kept, so the
    user is asked for its amount instead.
    """
    if part.amount is not None or base.amount is None:
        return False
    for field in ExtractedTransaction.model_fields:
        mine, theirs = getattr(part, field), getattr(base, field)
        if mine is not None and theirs is not None and str(mine).lower() != str(theirs).lower():
            return False
    return True


def _absorb(base: ExtractedTransaction, part: ExtractedTransaction) -> ExtractedTransaction:
    fills = {
        f: getattr(part, f)
        for f in ExtractedTransaction.model_fields
        if getattr(base, f) is None and getattr(part, f) is not None
    }
    return base.model_copy(update=fills)


def _merge_fragments(transactions: list[ExtractedTransaction]) -> list[ExtractedTransaction]:
    merged: list[ExtractedTransaction] = []
    for tx in transactions:
        if merged and _complements(merged[-1], tx):
            merged[-1] = _absorb(merged[-1], tx)
        else:
            merged.append(tx)
    if len(merged) > 1 and _complements(merged[1], merged[0]):  # a leading fragment
        merged = [_absorb(merged[1], merged[0]), *merged[2:]]
    return merged


def _normalise(tx: ExtractedTransaction, *, today: date, locale: str) -> ExtractedTransaction:
    updates: dict[str, object] = {}
    # A catch-all chosen by the model means "unknown": ask with one tap instead of filing
    # everything under Other. The user can still pick Other or skip.
    if tx.category in FALLBACK_SLUG.values():
        updates["category"] = None
    # Resolve the user's own date words deterministically (the same rule the drafts use).
    if tx.date_text and not tx.date:
        resolved = resolve_date_expression(
            tx.date_text, today, day_first=day_first_for_locale(locale)
        )
        if resolved is not None:
            updates["date"] = resolved.isoformat()
    return tx.model_copy(update=updates) if updates else tx


def _as_transfer(
    tx: ExtractedTransaction, hint: ExtractedTransaction | None
) -> ExtractedTransaction:
    """A transfer has only two accounts: no category, merchant or payment method.

    The parser's accounts fill the ones the model left empty.
    """
    fills = {
        f: getattr(hint, f)
        for f in ("account", "to_account")
        if hint is not None and getattr(tx, f) is None and getattr(hint, f)
    }
    return tx.model_copy(
        update={
            "type": "transfer",
            "category": None,
            "merchant": None,
            "payment_method": None,
            **fills,
        }
    )


_SHARING_FIELDS = ("participants", "payer", "split", "shares")


def _fill(tx: ExtractedTransaction, hint: ExtractedTransaction) -> ExtractedTransaction:
    updates = {
        f: getattr(hint, f) for f in _FILLABLE if getattr(tx, f) is None and getattr(hint, f)
    }
    if hint.type == "transfer":
        updates["type"] = "transfer"  # the parser's transfer phrasings are exact: they win
    if hint.participants and not tx.participants:
        # The model read an ordinary expense where the user named friends and a split. The
        # four sharing fields describe one thing, so they are taken together or not at all.
        updates.update({f: getattr(hint, f) for f in _SHARING_FIELDS})
        updates["type"] = "expense"
    kind = updates.get("type") or tx.type
    if tx.category is None and hint.category:
        definition = system_category(hint.category)
        if definition is not None and (kind is None or definition.kind == kind):
            updates["category"] = hint.category
    if tx.date is None and tx.date_text is None and hint.date_text:
        updates["date_text"], updates["date"] = hint.date_text, hint.date
    if tx.description is None and hint.description:
        updates["description"] = hint.description
    filled = tx.model_copy(update=updates) if updates else tx
    return _as_transfer(filled, hint) if filled.type == "transfer" else filled


def _account_not_merchant(
    tx: ExtractedTransaction, text: str, account_names: Sequence[str]
) -> ExtractedTransaction:
    """An account the user paid from or into is never the merchant.

    Otherwise "paid 300 from HDFC" would teach a merchant rule that files HDFC's spending
    under lunch's category.
    """
    if tx.type == "transfer" or not tx.merchant:
        return tx
    if tx.account:
        # The model named the account and also the merchant: they are the same words.
        return (
            tx.model_copy(update={"merchant": None})
            if same_account_name(tx.merchant, tx.account)
            else tx
        )
    said_from = re.search(rf"\b(?:from|into)\s+(?:my\s+)?{re.escape(tx.merchant)}\b", text, re.I)
    if said_from and could_mean_an_account(tx.merchant, account_names):
        return tx.model_copy(update={"account": tx.merchant, "merchant": None})
    return tx


def _participant_not_merchant(tx: ExtractedTransaction) -> ExtractedTransaction:
    """A friend the expense is shared with is never the merchant ("pizza with Jaymin")."""
    if tx.merchant and tx.merchant.casefold() in {p.casefold() for p in tx.participants}:
        return tx.model_copy(update={"merchant": None})
    return tx


def reconcile(
    understanding: TurnUnderstanding,
    text: str,
    *,
    today: date,
    locale: str,
    account_names: Sequence[str] = (),
    friend_names: Sequence[str] = (),
) -> TurnUnderstanding:
    if understanding.intent == "record_transactions" and understanding.transactions:
        transactions = _drop_duplicates(_merge_fragments(list(understanding.transactions)), text)
        hints = extract_transactions(text, today, locale, account_names, friend_names)
        unused = list(hints)
        filled = []
        for original in transactions:
            value = _value(original)
            match = next((h for h in unused if value is not None and _value(h) == value), None)
            if match is None and value is None and len(transactions) == len(hints) == 1:
                # Nothing to match by: the model read no amount, and the parser read the only one.
                match = unused[0]
            tx = _normalise(original, today=today, locale=locale)
            if match is not None:
                unused.remove(match)
                tx = _fill(tx, match)
            elif tx.type == "transfer":
                tx = _as_transfer(tx, None)
            filled.append(_participant_not_merchant(_account_not_merchant(tx, text, account_names)))
        return understanding.model_copy(update={"transactions": filled})

    if understanding.intent in ("search_transactions", "spending_summary"):
        hint = extract_search(text)
        search = understanding.search
        updates: dict[str, object] = {}
        if hint.type == "transfer" and (search is None or search.type != "transfer"):
            # "transfers" is unambiguous; a category or merchant does not apply to one.
            updates.update(type="transfer", category=None)
        elif hint.category and (search is None or search.category is None):
            updates["category"] = hint.category
        if hint.sort == "largest" and (search is None or search.sort != "largest"):
            updates["sort"] = "largest"  # "biggest/largest/highest" is unambiguous
        if updates:
            base = search or hint.model_copy(update={"sort": "recent", "limit": None, "text": None})
            return understanding.model_copy(update={"search": base.model_copy(update=updates)})
    return understanding
