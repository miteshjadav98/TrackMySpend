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
    merchant: str | None = None,
) -> CategoryChoice | None:
    """The category that files a chat draft, or None when the user has to be asked.

    `message` is what the user wrote; `picked` is their answer to a category
    clarification; `suggested` is the model's suggested category; `merchant_rule` is the
    category the user's merchant rule names for the draft's merchant and type. `merchant`
    is taken out of the message first, so "Cult Fitness" never names "Fitness".
    """
    if picked is not None:
        return CategoryChoice(picked, "picked")
    # The model's suggestion counts as the user's own words when the message names it.
    if suggested is not None and names_category(_without_merchant(message, merchant), suggested):
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
    said = {_stem(word) for word in _words(message)}
    name = {_stem(word) for word in _words(category.name)}
    says_whole_name = name <= said
    says_a_distinctive_word = bool((name - _GENERIC_WORDS) & said)
    return says_whole_name or says_a_distinctive_word


def _words(text: str) -> set[str]:
    return set(_tokens(text))


def _tokens(text: str) -> list[str]:
    # Runs of letters and digits, so "&" or "!" is never a word.
    return re.findall(r"[^\W_]+", text.casefold())


def _stem(word: str) -> str:
    """Singular form of a simple plural, so "grocery" names Groceries and "hobbies" names Hobby."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("sses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _without_merchant(message: str, merchant: str | None) -> str:
    """The message with the merchant's own words cut out once: they name a shop, not a category."""
    words, merchant_words = _tokens(message), _tokens(merchant or "")
    size = len(merchant_words)
    for start in range(len(words) - size + 1 if size else 0):
        if words[start : start + size] == merchant_words:
            return " ".join(words[:start] + words[start + size :])
    return message
