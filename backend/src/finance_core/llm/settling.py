"""Reads settlements and balance questions from the user's own words.

Part of the offline parser. It finds who paid whom and how much, and which friend a balance
question is about. Whether "paid Jaymin 500" really is a settlement depends on the balance,
which only the database knows, so that decision is made later in the workflow, never here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from finance_core.llm.schemas import BalanceSpec
from finance_core.llm.sharing import _NOT_NAMES, _tidy_name
from finance_core.money import find_amounts

_I = re.IGNORECASE
_NAME = r"[A-Za-z][\w'-]*"
# One or two words, but never swallowing the "back" of "paid Jaymin back 500".
_FRIEND = rf"(?P<name>{_NAME}(?:\s+(?!back\b){_NAME})?)"
_AMOUNT_WORD = r"\S*\d\S*"

# "Jaymin paid me 500", "Riya gave me back 1,200"
_FRIEND_PAID_ME = re.compile(
    rf"^\W*{_FRIEND}\s+(?:paid|gave|returned|sent|transferred|repaid)\s+me\b", _I
)
# "paid Jaymin 500", "I paid back Jaymin 500", "paid Jaymin back 500"
_I_PAID_FRIEND = re.compile(
    rf"^\W*(?:i\s+)?(?:paid|pay|gave|returned|sent|transferred|repaid)\s+(?:back\s+)?{_FRIEND}\b",
    _I,
)
# "paid 500 to Jaymin"
_I_PAID_AMOUNT_TO_FRIEND = re.compile(
    rf"^\W*(?:i\s+)?(?:paid|gave|returned|sent|transferred|repaid)\s+(?:back\s+)?{_AMOUNT_WORD}"
    rf"\s+to\s+{_FRIEND}\b",
    _I,
)
_PURPOSE = re.compile(
    r"\bfor\s+(?P<what>.+?)(?=\s+(?:to|into|from|using|via|yesterday|today)\b|[.!?]*\s*$)", _I
)

_BALANCE_OF_ONE = (
    re.compile(rf"\bhow much (?:does|did|do)\s+{_FRIEND}\s+owe\s+me\b", _I),
    re.compile(rf"\bhow much (?:do|did|will) i owe\s+{_FRIEND}", _I),
    re.compile(rf"\bwhat (?:do|does) i owe\s+{_FRIEND}", _I),
    re.compile(rf"\bdoes\s+{_FRIEND}\s+owe\s+me\b", _I),
    re.compile(rf"\bdo i owe\s+{_FRIEND}", _I),
    re.compile(rf"\b(?:balance|balances)\s+(?:with|for)\s+{_FRIEND}", _I),
)
_BALANCE_OF_ALL = re.compile(
    r"\bwho owes\b|\bwho do i owe\b|\bwho (?:all )?owe\b|\b(?:what|how much) do my friends owe\b"
    r"|\bhow much do i owe\b|\b(?:my|friend|friends|all)\s+balances?\b|\bwhat do i owe\b",
    _I,
)


@dataclass(frozen=True, slots=True)
class PayingBack:
    """Money one side handed to the other, as the user said it."""

    friend: str
    direction: Literal["friend_paid_me", "i_paid_friend"]
    amount: Decimal
    currency: str | None
    purpose: str | None  # what it was for, when the user said ("his old phone")


def _is_known(name: str, friend_names: Sequence[str]) -> bool:
    """True when `name` is a friend's name, or the first word of one."""
    said = name.casefold().split()
    return any(set(said) <= set(friend.casefold().split()) for friend in friend_names)


def _usable_name(name: str) -> str | None:
    """The name tidied, or None when it is a word like "me" or "everyone"."""
    if name.casefold() in _NOT_NAMES or name.split()[0].casefold() in _NOT_NAMES:
        return None
    return _tidy_name(name)


def read_paying_back(text: str, friend_names: Sequence[str] = ()) -> PayingBack | None:
    """The settlement in `text`, or None when the message is not about paying a friend.

    "X paid me N" names any X, because someone paying the user is nothing else. "paid X N" needs
    X to be one of the user's friends: "paid electricity 1200" is an expense.
    """
    mentions = find_amounts(text)
    if not mentions:
        return None
    direction: Literal["friend_paid_me", "i_paid_friend"]
    if match := _FRIEND_PAID_ME.match(text):
        direction = "friend_paid_me"
    elif match := _I_PAID_AMOUNT_TO_FRIEND.match(text) or _I_PAID_FRIEND.match(text):
        direction = "i_paid_friend"
    else:
        return None
    friend = _usable_name(match.group("name"))
    if friend is None:
        return None
    if direction == "i_paid_friend" and not _is_known(friend, friend_names):
        return None
    purpose = _PURPOSE.search(text)
    return PayingBack(
        friend=friend,
        direction=direction,
        amount=mentions[0].value,
        currency=mentions[0].currency,
        purpose=purpose.group("what").strip() if purpose else None,
    )


def read_balance_question(text: str, friend_names: Sequence[str] = ()) -> BalanceSpec | None:
    """The balance question in `text`: one friend, or every friend when none is named."""
    for pattern in _BALANCE_OF_ONE:
        if match := pattern.search(text):
            return BalanceSpec(friend=_usable_name(match.group("name")))
    if _BALANCE_OF_ALL.search(text):
        return BalanceSpec(friend=None)
    return None
