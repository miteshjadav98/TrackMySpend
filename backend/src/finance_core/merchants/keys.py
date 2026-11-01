"""Merchant keys: one spelling-proof name per merchant.

"SWIGGY", "Swiggy!" and " swiggy " are the same merchant, so a merchant rule is stored and
looked up by this key rather than by the name as typed.
"""

from __future__ import annotations

import unicodedata


def _is_punctuation(character: str) -> bool:
    # Unicode categories P* (punctuation) and S* (symbols such as "&" or "+").
    return unicodedata.category(character)[0] in ("P", "S")


def merchant_key(name: str) -> str:
    """The merchant name case-folded, with punctuation removed and whitespace collapsed."""
    folded = name.casefold()
    without_punctuation = "".join(c for c in folded if not _is_punctuation(c))
    return " ".join(without_punctuation.split())
