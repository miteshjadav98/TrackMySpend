"""Picking a merchant out of a bank narration."""

from __future__ import annotations

import pytest

from finance_core.imports.merchant import extract_merchant


@pytest.mark.parametrize(
    ("narration", "merchant"),
    [
        ("UPI-SWIGGY-swiggy@icici-ICIC0000001-627412345678-Food order", "SWIGGY"),
        ("UPI/DR/627412345680/ZOMATO/yesbank/Food", "ZOMATO"),
        ("NEFT CR-HDFC0000001-ACME CORP-TEST USER-SALARY OCT", "ACME CORP"),
        ("BY TRANSFER-NEFT*SBIN0000001*N27412*ACME CORP SALARY", "ACME CORP SALARY"),
        ("POS 4291XXXXXXXX1234 BIGBASKET", "BIGBASKET"),
    ],
)
def test_the_merchant_is_the_name_in_the_narration_not_the_reference_numbers(
    narration: str, merchant: str
) -> None:
    assert extract_merchant(narration) == merchant


def test_a_narration_that_is_all_reference_numbers_has_no_merchant() -> None:
    assert extract_merchant("ATW-4291XXXXXXXX1234-627412345678") is None


def test_an_empty_narration_has_no_merchant() -> None:
    assert extract_merchant("   ") is None
    assert extract_merchant(None) is None
