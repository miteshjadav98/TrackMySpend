"""Picking the merchant out of a bank narration.

This is a first, small version so merchant rules can already apply to imported rows: it skips
channel words (UPI, NEFT, POS), bank codes and reference numbers and returns the first name
left. A fuller set of Indian narration formats replaces it later without changing callers.
"""

from __future__ import annotations

import re

_PARTS = re.compile(r"[-/*]")
_CHANNEL_WORDS = re.compile(
    r"^(?:(?:upi|neft|imps|rtgs|pos|atw|ach|by transfer|to transfer|cr|dr)\b\s*)+", re.IGNORECASE
)
_IFSC = re.compile(r"^[A-Za-z]{4}0[A-Za-z0-9]{6}$")
# A token that is a reference number, a masked card number or a UPI handle, not a name.
_NOT_A_NAME_WORD = re.compile(r"\d{4,}|x{4,}|@", re.IGNORECASE)
MAX_MERCHANT_LENGTH = 200


def extract_merchant(narration: str | None) -> str | None:
    """The merchant named in the narration, or None when it holds only reference numbers."""
    for part in _PARTS.split(narration or ""):
        words = _CHANNEL_WORDS.sub("", part.strip()).split()
        name = " ".join(word for word in words if not _NOT_A_NAME_WORD.search(word))
        if name and not _IFSC.match(name):
            return name[:MAX_MERCHANT_LENGTH]
    return None
