"""Exact money handling.

Rules this module enforces:
- Amounts are `Decimal` in memory and integer *minor units* (paise, cents) in storage,
  always paired with an explicit ISO 4217 currency. No binary floats anywhere.
- Converting to minor units never rounds silently: excess precision is an error, so the
  caller has to ask the user ("did you mean ₹350.56?") instead of guessing.
- Values in different currencies are never added together.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from babel.numbers import format_currency

# ISO 4217 minor-unit exponents for the currencies we accept. An explicit allowlist keeps
# validation predictable (no surprises from locale data) and is trivial to extend.
CURRENCY_EXPONENTS: dict[str, int] = {
    "INR": 2, "USD": 2, "EUR": 2, "GBP": 2, "AED": 2, "SGD": 2, "AUD": 2, "CAD": 2,
    "CHF": 2, "CNY": 2, "HKD": 2, "NZD": 2, "SAR": 2, "QAR": 2, "MYR": 2, "THB": 2,
    "IDR": 2, "LKR": 2, "NPR": 2, "BDT": 2, "PKR": 2, "ZAR": 2, "SEK": 2, "NOK": 2,
    "DKK": 2, "JPY": 0, "KRW": 0, "VND": 0, "BHD": 3, "KWD": 3, "OMR": 3,
}  # fmt: skip
SUPPORTED_CURRENCIES = frozenset(CURRENCY_EXPONENTS)

# Upper bound on a single transaction (10^15 minor units, e.g. ₹10 trillion): catches
# parsing accidents long before they could overflow BIGINT.
MAX_AMOUNT_MINOR = 10**15

# Symbols and words users type, mapped to ISO codes. Ambiguous symbols ("¥", "kr") are
# deliberately absent: an unknown currency triggers a question, never a guess.
_CURRENCY_ALIASES: dict[str, str] = {
    "₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "rupee": "INR", "rupees": "INR",
    "$": "USD", "usd": "USD", "dollar": "USD", "dollars": "USD", "us$": "USD",
    "€": "EUR", "eur": "EUR", "euro": "EUR", "euros": "EUR",
    "£": "GBP", "gbp": "GBP", "pound": "GBP", "pounds": "GBP",
    "aed": "AED", "dirham": "AED", "dirhams": "AED",
    "sgd": "SGD", "s$": "SGD", "aud": "AUD", "a$": "AUD", "cad": "CAD", "c$": "CAD",
    "jpy": "JPY", "yen": "JPY",
}  # fmt: skip

_MULTIPLIERS: dict[str, Decimal] = {
    "k": Decimal(1_000), "thousand": Decimal(1_000),
    "l": Decimal(100_000), "lac": Decimal(100_000), "lacs": Decimal(100_000),
    "lakh": Decimal(100_000), "lakhs": Decimal(100_000),
    "cr": Decimal(10_000_000), "crore": Decimal(10_000_000), "crores": Decimal(10_000_000),
    "m": Decimal(1_000_000), "mn": Decimal(1_000_000), "million": Decimal(1_000_000),
}  # fmt: skip

_NUMBER = r"(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?|\.\d+"
_MULTIPLIER = r"k|thousand|lacs?|lakhs?|l|crores?|cr|million|mn|m"
_SYMBOL = r"₹|rs\.?|inr|us\$|s\$|a\$|c\$|\$|€|£|usd|eur|gbp|aed|sgd|aud|cad|jpy"
_WORD_CURRENCY = r"rupees?|dollars?|euros?|pounds?|dirhams?|yen"

_STANDALONE_AMOUNT = re.compile(
    rf"^\s*(?P<sym>{_SYMBOL})?\s*(?P<num>{_NUMBER})\s*(?P<mult>{_MULTIPLIER})?\s*"
    rf"(?P<code>{_SYMBOL}|{_WORD_CURRENCY})?\s*(?:only)?\s*$",
    re.IGNORECASE,
)

# Numbers that are clearly not money: times, ordinals, quantities, durations.
_NOT_MONEY_SUFFIX = (
    r"(?!\s?(?:am|pm|a\.m\.|p\.m\.|st|nd|rd|th|hrs?|hours?|mins?|minutes?|secs?|"
    r"kgs?|kms?|gms?|grams?|litres?|liters?|ml|%|pcs?|pieces?|people|persons?|"
    r"days?|weeks?|months?|years?|yrs?|nights?|times?|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|"
    r"sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\b)"
)

# Finds amounts inside free text: "spent ₹350 on", "paid rs 1,200", "got 2 lakh salary".
# Digits that belong to dates ("12/10", "2026-10-01") or times ("7:30") are skipped.
_EMBEDDED_AMOUNT = re.compile(
    rf"(?<![\w./:-])(?P<sym>{_SYMBOL})?\s?(?P<num>{_NUMBER})(?![\d/:-]){_NOT_MONEY_SUFFIX}"
    rf"(?:\s?(?P<mult>{_MULTIPLIER})(?![a-z]))?"
    rf"(?:\s?(?P<code>{_SYMBOL}|{_WORD_CURRENCY})(?![a-z]))?",
    re.IGNORECASE,
)


class MoneyError(ValueError):
    """An amount or currency that cannot be represented exactly."""


def exponent(currency: str) -> int:
    try:
        return CURRENCY_EXPONENTS[currency]
    except KeyError:
        raise MoneyError(f"Unsupported currency: {currency}") from None


def normalize_currency(raw: str | None) -> str | None:
    """Map an ISO code, symbol or currency word to a supported ISO code (or None)."""
    if raw is None:
        return None
    token = raw.strip().lower()
    if not token:
        return None
    if token.upper() in SUPPORTED_CURRENCIES:
        return token.upper()
    return _CURRENCY_ALIASES.get(token)


def to_minor(amount: Decimal, currency: str) -> int:
    """Convert to integer minor units without rounding (raises on excess precision)."""
    if not amount.is_finite():
        raise MoneyError("Amount must be a finite number")
    scaled = amount.scaleb(exponent(currency))
    if scaled != scaled.to_integral_value():
        raise MoneyError(
            f"{currency} supports at most {exponent(currency)} decimal places",
        )
    minor = int(scaled)
    if minor <= 0:
        raise MoneyError("Amount must be greater than zero")
    if minor > MAX_AMOUNT_MINOR:
        raise MoneyError("Amount is larger than the maximum allowed")
    return minor


def from_minor(minor: int, currency: str) -> Decimal:
    return Decimal(minor).scaleb(-exponent(currency))


@dataclass(frozen=True, slots=True)
class Money:
    minor: int
    currency: str

    @classmethod
    def of(cls, amount: Decimal | str, currency: str) -> Money:
        try:
            value = amount if isinstance(amount, Decimal) else Decimal(amount)
        except InvalidOperation:
            raise MoneyError(f"Not a valid amount: {amount!r}") from None
        return cls(to_minor(value, currency), currency)

    @property
    def amount(self) -> Decimal:
        return from_minor(self.minor, self.currency)

    def __add__(self, other: Money) -> Money:
        if other.currency != self.currency:
            raise MoneyError("Cannot add amounts in different currencies")
        return Money(self.minor + other.minor, self.currency)


def _apply_multiplier(number: Decimal, multiplier: str | None) -> Decimal:
    if not multiplier:
        return number
    return number * _MULTIPLIERS[multiplier.lower()]


def _to_decimal(number_text: str) -> Decimal | None:
    try:
        return Decimal(number_text.replace(",", ""))
    except InvalidOperation:
        return None


def parse_amount(text: str) -> Decimal | None:
    """Parse an amount the user typed on its own.

    Accepts "350", "₹1,23,456.50", "1.5k", "2 lakh", "1 crore", "$20", "20 usd".
    Returns None when the text is not just an amount, or the amount is not positive.
    """
    match = _STANDALONE_AMOUNT.match(text or "")
    if not match:
        return None
    number = _to_decimal(match.group("num"))
    if number is None:
        return None
    value = _apply_multiplier(number, match.group("mult"))
    return value if value > 0 else None


def parse_amount_with_currency(text: str) -> tuple[Decimal, str | None] | None:
    """Like `parse_amount`, but also returns a currency if one was written."""
    match = _STANDALONE_AMOUNT.match(text or "")
    if not match:
        return None
    number = _to_decimal(match.group("num"))
    if number is None:
        return None
    value = _apply_multiplier(number, match.group("mult"))
    if value <= 0:
        return None
    currency = normalize_currency(match.group("sym")) or normalize_currency(match.group("code"))
    return value, currency


@dataclass(frozen=True, slots=True)
class AmountMention:
    value: Decimal
    currency: str | None
    start: int
    end: int
    has_marker: bool  # a currency symbol/word or multiplier was attached


def find_amounts(text: str) -> list[AmountMention]:
    """All amount-like numbers in free text, in order of appearance."""
    mentions: list[AmountMention] = []
    for match in _EMBEDDED_AMOUNT.finditer(text or ""):
        number = _to_decimal(match.group("num"))
        if number is None:
            continue
        value = _apply_multiplier(number, match.group("mult"))
        if value <= 0:
            continue
        sym, code, mult = match.group("sym"), match.group("code"), match.group("mult")
        currency = normalize_currency(sym) or normalize_currency(code)
        mentions.append(
            AmountMention(
                value=value,
                currency=currency,
                start=match.start(),
                end=match.end(),
                has_marker=bool(sym or code or mult),
            )
        )
    return mentions


def amount_is_grounded(amount: Decimal, source_text: str) -> bool:
    """True if `amount` literally appears in what the user wrote.

    The LLM is allowed to *read* amounts, never to *invent* them. An extracted amount
    that is not present in the text (e.g. spelled out, or hallucinated) must be
    confirmed with the user before it is saved.
    """
    return any(mention.value == amount for mention in find_amounts(source_text))


def babel_locale(locale: str) -> str:
    return locale.replace("-", "_")


def format_money(minor: int, currency: str, locale: str = "en-IN") -> str:
    """Locale-aware display string, e.g. ₹1,23,456.50 for en-IN."""
    return str(format_currency(from_minor(minor, currency), currency, locale=babel_locale(locale)))
