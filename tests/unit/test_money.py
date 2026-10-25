from __future__ import annotations

from decimal import Decimal

import pytest

from finance_core.money import (
    Money,
    MoneyError,
    amount_is_grounded,
    find_amounts,
    format_money,
    normalize_currency,
    parse_amount,
    parse_amount_with_currency,
    to_minor,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("350", "350"),
        ("₹1,23,456.50", "123456.50"),
        ("1,234,567", "1234567"),
        ("1.5k", "1500"),
        ("2 lakh", "200000"),
        ("1 crore", "10000000"),
        ("$20", "20"),
        ("20 usd", "20"),
        ("rs. 99", "99"),
        ("350 rupees only", "350"),
        (".5", "0.5"),
    ],
)
def test_parse_amount_accepts_common_formats(text: str, expected: str) -> None:
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["0", "-5", "abc", "", "12/10", "five hundred"])
def test_parse_amount_rejects_non_amounts(text: str) -> None:
    assert parse_amount(text) is None


def test_parse_amount_with_currency() -> None:
    assert parse_amount_with_currency("₹350") == (Decimal(350), "INR")
    assert parse_amount_with_currency("20 eur") == (Decimal(20), "EUR")
    assert parse_amount_with_currency("350") == (Decimal(350), None)


def test_to_minor_is_exact_and_never_rounds() -> None:
    assert to_minor(Decimal("350.5"), "INR") == 35050
    assert to_minor(Decimal("500"), "JPY") == 500
    assert to_minor(Decimal("1.234"), "BHD") == 1234
    with pytest.raises(MoneyError, match="decimal places"):
        to_minor(Decimal("350.555"), "INR")
    with pytest.raises(MoneyError, match="decimal places"):
        to_minor(Decimal("10.5"), "JPY")
    with pytest.raises(MoneyError):
        to_minor(Decimal(0), "INR")
    with pytest.raises(MoneyError):
        to_minor(Decimal(10) ** 20, "INR")
    with pytest.raises(MoneyError, match="Unsupported"):
        to_minor(Decimal(1), "XYZ")


def test_money_refuses_to_mix_currencies() -> None:
    total = Money.of("10.25", "INR") + Money.of("0.75", "INR")
    assert total == Money(1100, "INR")
    with pytest.raises(MoneyError):
        _ = Money.of("1", "INR") + Money.of("1", "USD")


def test_find_amounts_skips_dates_times_and_quantities() -> None:
    text = "dinner at 7pm for 350, bought 2 kg apples for 180 on 12/10 and 12th oct"
    assert [m.value for m in find_amounts(text)] == [Decimal(350), Decimal(180)]


def test_grounding_detects_invented_amounts() -> None:
    text = "spent ₹1,200 on electricity"
    assert amount_is_grounded(Decimal(1200), text)
    assert not amount_is_grounded(Decimal(1500), text)
    assert not amount_is_grounded(Decimal(350), "three fifty on dinner")


def test_format_money_uses_locale_grouping() -> None:
    assert format_money(12345650, "INR", "en-IN") == "₹1,23,456.50"
    assert format_money(123456789, "USD", "en-US") == "$1,234,567.89"
    assert format_money(-35000, "INR", "en-IN") == "-₹350.00"


def test_normalize_currency() -> None:
    assert normalize_currency("₹") == "INR"
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("dollars") == "USD"
    assert normalize_currency("¥") is None  # ambiguous: ask, don't guess
