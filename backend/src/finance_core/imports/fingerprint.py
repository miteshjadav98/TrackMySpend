"""Row fingerprints: the idempotency key that makes a re-import skip rows it already saved.

A fingerprint hashes the account, date, amount, direction and wording of a row, plus how many
identical rows came before it in the file. The same file imported twice therefore gives the
same keys, while two genuinely identical payments in one file keep different keys.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Sequence
from datetime import date

from finance_core.imports.rows import ParsedRow


def normalise_description(description: str | None) -> str:
    return " ".join((description or "").casefold().split())


def row_fingerprint(
    account_id: uuid.UUID,
    occurred_on: date,
    amount_minor: int,
    direction: str,
    description: str | None,
    occurrence: int,
) -> str:
    parts = [
        str(account_id), occurred_on.isoformat(), str(amount_minor), direction,
        normalise_description(description), str(occurrence),
    ]  # fmt: skip
    # "imp1" versions the recipe; the idempotency_key column holds 128 characters.
    return "imp1:" + hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def assign_fingerprints(account_id: uuid.UUID, rows: Sequence[ParsedRow]) -> list[str | None]:
    """One fingerprint per row, in order; None for a row that could not be read."""
    seen: Counter[tuple[date, int, str, str]] = Counter()
    fingerprints: list[str | None] = []
    for row in rows:
        if row.problem is not None or row.occurred_on is None or row.amount_minor is None:
            fingerprints.append(None)
            continue
        assert row.direction is not None
        identity = (
            row.occurred_on, row.amount_minor, row.direction,
            normalise_description(row.description),
        )  # fmt: skip
        seen[identity] += 1
        fingerprints.append(
            row_fingerprint(
                account_id,
                row.occurred_on,
                row.amount_minor,
                row.direction,
                row.description,
                seen[identity],
            )
        )
    return fingerprints
