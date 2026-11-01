"""Split arithmetic for shared expenses, as pure functions on integer minor units.

A person is keyed by whatever the caller likes (the service uses `None` for the recorder and
a friend's id for a friend), so these functions need no database and are easy to test.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

from finance_core.errors import ValidationFailedError


def equal_split[Person: Hashable](
    total_minor: int, people: Sequence[Person], *, payer: Person
) -> dict[Person, int]:
    """Give everyone the floor of total / people; the payer also takes the leftover units.

    The payer takes the leftover because they handed over the whole amount, so the extra
    minor unit is theirs to absorb rather than a friend's to owe.
    """
    each = total_minor // len(people)
    if each < 1:
        raise ValidationFailedError(
            "That amount is too small to split between this many people.",
            details={"field": "split"},
        )
    shares = {person: each for person in people}
    shares[payer] += total_minor - each * len(people)
    return shares


def exact_split[Person: Hashable](
    total_minor: int, amounts: Mapping[Person, int]
) -> dict[Person, int]:
    """Keep the amounts as given, after checking each is positive and they sum to the total."""
    if any(amount < 1 for amount in amounts.values()):
        raise ValidationFailedError(
            "Every share must be more than zero.", details={"field": "split"}
        )
    given = sum(amounts.values())
    if given != total_minor:
        raise ValidationFailedError(
            "The shares must add up to the total.",
            details={"field": "split", "totalMinor": total_minor, "sharesMinor": given},
        )
    return dict(amounts)
