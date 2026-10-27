"""Merchant keys: the spelling-proof name a merchant rule is filed under."""

from __future__ import annotations

from finance_core.merchants.keys import merchant_key


def test_case_punctuation_and_spacing_do_not_change_the_key() -> None:
    assert merchant_key("SWIGGY") == "swiggy"
    assert merchant_key("Swiggy!") == "swiggy"
    assert merchant_key("  Ramesh   Stores. ") == "ramesh stores"
    assert merchant_key("Domino's") == "dominos"
