"""Account names as people say them: find the account a name means, and guess a new one's kind.

Pure functions, so the chat's account rules are unit-tested without a database.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol, TypeVar

from finance_core.accounts.schemas import AccountKindField

# Names that say what kind of account it is, not which one: "withdrew 2000" goes to "Cash".
_KIND_WORDS: dict[frozenset[str], AccountKindField] = {
    frozenset({"cash"}): "cash",
    frozenset({"credit", "card"}): "credit_card",
    frozenset({"card"}): "credit_card",
}
_WALLETS = re.compile(r"\b(paytm|phone\s?pe|g\s?pay|google pay|amazon pay|mobikwik|wallet)\b")

class _Named(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def kind(self) -> str: ...


AccountLike = TypeVar("AccountLike", bound=_Named)


def _words(text: str) -> set[str]:
    # Runs of letters and digits, so "HDFC-Savings" and "hdfc savings" are the same words.
    return set(re.findall(r"[^\W_]+", text.casefold()))


def resolve_account_name(name: str, accounts: Sequence[AccountLike]) -> AccountLike | None:
    """The one account `name` means, or None when it means none or several.

    An exact name, ignoring case, wins. Otherwise one account whose words contain the name's
    words, or are contained in them ("HDFC" and "HDFC Savings"). A bare kind ("cash",
    "credit card") means the user's only account of that kind.
    """
    said = name.strip().casefold()
    if not said:
        return None
    exact = [a for a in accounts if a.name.casefold() == said]
    if len(exact) == 1:
        return exact[0]
    said_words = _words(said)
    overlapping = [
        a for a in accounts if said_words <= _words(a.name) or _words(a.name) <= said_words
    ]
    if len(overlapping) == 1:
        return overlapping[0]
    if not overlapping and (kind := _KIND_WORDS.get(frozenset(said_words))):
        of_kind = [a for a in accounts if a.kind == kind]
        if len(of_kind) == 1:
            return of_kind[0]
    return None


def infer_account_kind(name: str) -> AccountKindField:
    """The kind of a new account the user named in chat: cash, credit card, wallet or bank."""
    lowered = name.casefold()
    words = _words(lowered)
    if "cash" in words:
        return "cash"
    if "debit" in words:
        return "bank"  # a debit card spends from a bank account
    if "credit" in words or "card" in words:
        return "credit_card"
    if _WALLETS.search(lowered):
        return "wallet"
    return "bank"
