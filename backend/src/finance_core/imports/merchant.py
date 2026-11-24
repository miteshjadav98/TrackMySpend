"""Read merchant labels from Indian bank statement narrations."""

from __future__ import annotations

import re

_CHANNEL = re.compile(
    r"^(?:(?:by|to) transfer|card (?:purchase|payment|txn)|"
    r"(?:dc|cc|debit card|credit card) (?:pur(?:chase)?|txn)|"
    r"(?:(?:(?:debit|credit) )?card|visa|mastercard|rupay)(?=\s*(?:[-/*|]|$))|"
    r"upi|neft|imps|rtgs|pos|ecom|ecm|atm|atw|ach|nach)\b[\s.:#]*",
    re.IGNORECASE,
)
_ROUTING_PREFIX = re.compile(
    r"^(?:p2[apm]|a2a|inward|outward|debit|credit|(?:dr|cr)(?=\s*(?:[:#]|\d|$))|"
    r"transfer|nfs|(?:cash )?(?:wdl|withdrawal)(?: at)?|(?:payment|vpa)\s*$|"
    r"purchase|pur|txn(?:\s+id)?|(?:utr|rrn|ref)(?:\s+no\.?)?)\b[\s.:#]*",
    re.IGNORECASE,
)
_REFERENCE = re.compile(
    r"(?:[a-z]{4}0[a-z0-9]{6}|[a-z]{1,12}\d{5,}[a-z0-9]*|\d*x{2,}\d*|"
    r"(?:₹|rs\.?|inr)?\d[\d,.]*)",
    re.IGNORECASE,
)
_STRUCTURED_PARTS = re.compile(r"[-/*|]")
_UNSTRUCTURED_PARTS = re.compile(r"[/*|]")
MAX_MERCHANT_LENGTH = 200


def _is_name_word(word: str) -> bool:
    token = word.strip(",.:()#")
    return any(char.isalpha() for char in token) and (
        "@" not in token and _REFERENCE.fullmatch(token) is None
    )


def _name(part: str, *, structured: bool) -> str:
    """Remove channel and reference tokens before reading the first name."""
    words = []
    remaining = part.strip()
    while remaining:
        if structured and (prefix := _CHANNEL.match(remaining) or _ROUTING_PREFIX.match(remaining)):
            remaining = remaining[prefix.end() :]
            continue
        word, *tail = remaining.split(maxsplit=1)
        remaining = tail[0] if tail else ""
        if _is_name_word(word):
            words.append(word)
            break

    words.extend(word for word in remaining.split() if _is_name_word(word))
    return " ".join(words).strip(" .,:#")


def extract_merchant(narration: str | None) -> str | None:
    """Get the first readable merchant or ATM label after the bank's routing fields."""
    text = (narration or "").strip()
    structured = _CHANNEL.match(text) is not None
    splitter = _STRUCTURED_PARTS if structured else _UNSTRUCTURED_PARTS
    for part in splitter.split(text):
        if name := _name(part, structured=structured):
            return name[:MAX_MERCHANT_LENGTH]
    return None
