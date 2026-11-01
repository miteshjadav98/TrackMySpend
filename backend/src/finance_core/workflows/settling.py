"""Decides what a settlement message turns into, from the user's friends and their balances.

"Paid Jaymin 500" is ambiguous: it may be paying back what is owed, or paying a person for
something. The model only reads the words; this module makes the call using the balances the
database worked out. Nothing here touches the database or does arithmetic on money.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from finance_core.friends.names import matching_friends
from finance_core.friends.schemas import FriendView
from finance_core.llm.schemas import ExtractedTransaction, SettlementSpec

AskReason = Literal["unknown_friend", "ambiguous_friend", "no_amount", "no_friend", "no_direction"]


@dataclass(frozen=True, slots=True)
class SettleChoice:
    """What to do with a settlement message: record it, record an expense instead, or ask."""

    kind: Literal["settle", "expense", "ask"]
    friend: FriendView | None = None
    reason: AskReason | None = None
    options: list[str] = field(default_factory=list)  # names to pick from when ambiguous


def _has_valid_amount(spec: SettlementSpec) -> bool:
    try:
        return spec.amount is not None and Decimal(spec.amount) > 0
    except InvalidOperation:
        return False


def _owes_in(friend: FriendView, currency: str) -> bool:
    """True when the balance with this friend is not zero in this currency."""
    return any(b.currency == currency and b.amount_minor != 0 for b in friend.balances)


def choose_settlement(
    spec: SettlementSpec, friends: list[FriendView], base_currency: str
) -> SettleChoice:
    """Record the settlement, fall back to an expense, or ask what is missing.

    "X paid me" is always a settlement. "I paid X" is one only when X is a friend, the user
    named nothing it was for, and the balance with X in that currency is not zero.
    """
    if not _has_valid_amount(spec):
        return SettleChoice("ask", reason="no_amount")
    if not spec.friend:
        return SettleChoice("ask", reason="no_friend")
    if spec.direction is None:
        return SettleChoice("ask", reason="no_direction")
    matches = matching_friends(spec.friend, friends)
    if spec.direction == "i_paid_friend":
        if spec.purpose or len(matches) != 1:
            return SettleChoice("expense")  # "paid Ramesh 2000 for his old phone", or a shop
        currency = (spec.currency or base_currency).upper()
        if not _owes_in(matches[0], currency):
            return SettleChoice("expense")
        return SettleChoice("settle", friend=matches[0])
    if not matches:
        return SettleChoice("ask", reason="unknown_friend")
    if len(matches) > 1:
        return SettleChoice("ask", reason="ambiguous_friend", options=[f.name for f in matches])
    return SettleChoice("settle", friend=matches[0])


def expense_from_settlement(spec: SettlementSpec) -> ExtractedTransaction:
    """The expense a "paid X N" message is when it is not a settlement, with X as merchant."""
    return ExtractedTransaction(
        type="expense",
        amount=spec.amount,
        currency=spec.currency,
        merchant=spec.friend,
        description=spec.purpose.title() if spec.purpose else None,
        account=spec.account,
        date_text=spec.date_text,
        date=spec.date,
    )
