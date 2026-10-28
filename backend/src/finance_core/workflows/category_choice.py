"""Category precedence: which category files a chat draft.

In one sentence, for users: if you pick or name a category, I use it; otherwise I use what
you used last time for that merchant; otherwise I guess, or ask.

Pure and deterministic, so every level is unit-tested without a model or a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

CategorySource = Literal["picked", "named", "merchant_rule", "model"]

# Words in category names that say nothing on their own: "received 5000" does not name
# "Gifts Received", "income" does not name "Rental Income", and "and" or "other" name nothing.
_GENERIC_WORDS = frozenset({"and", "income", "other", "received"})


@dataclass(frozen=True, slots=True)
class CategoryOption:
    """One of the user's categories that could file a draft."""

    id: str
    name: str
    is_fallback: bool = False  # "Other" or "Other income"


@dataclass(frozen=True, slots=True)
class CategoryChoice:
    """The category that files a draft, and which precedence level chose it."""

    category: CategoryOption
    source: CategorySource


def choose_category(
    message: str,
    *,
    picked: CategoryOption | None,
    suggested: CategoryOption | None,
    merchant_rule: CategoryOption | None,
) -> CategoryChoice | None:
    """The category that files a chat draft, or None when the user has to be asked.

    `message` is what the user wrote; `picked` is their answer to a category
    clarification; `suggested` is the model's suggested category; `merchant_rule` is the
    category the user's merchant rule names for the draft's merchant and type.
    """
    if picked is not None:
        return CategoryChoice(picked, "picked")
    # The model's suggestion counts as the user's own words when the message names it.
    if suggested is not None and names_category(message, suggested):
        return CategoryChoice(suggested, "named")
    if merchant_rule is not None:
        return CategoryChoice(merchant_rule, "merchant_rule")
    if suggested is not None:
        return CategoryChoice(suggested, "model")
    return None


def names_category(message: str, category: CategoryOption) -> bool:
    """True when the message names the category, as whole words: its whole name, or a
    distinctive word of it ("Food" for "Food & Dining"). A fallback category never counts.
    """
    if category.is_fallback:
        return False
    said = _words(message)
    name = _words(category.name)
    says_whole_name = name <= said
    says_a_distinctive_word = bool((name - _GENERIC_WORDS) & said)
    return says_whole_name or says_a_distinctive_word


def _words(text: str) -> set[str]:
    # Runs of letters and digits, so "&" or "!" is never a word.
    return set(re.findall(r"[^\W_]+", text.casefold()))
