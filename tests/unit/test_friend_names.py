"""Friend names as people say them in chat, without a database."""

from __future__ import annotations

from dataclasses import dataclass

from finance_core.friends.names import matching_friends, resolve_friend_name


@dataclass(frozen=True)
class Pal:
    """Just enough of a friend for name matching."""

    name: str


JAYMIN = Pal("Jaymin Shah")
RIYA = Pal("Riya")
OTHER_JAYMIN = Pal("Jaymin Patel")


def test_an_exact_name_ignoring_case_is_that_friend() -> None:
    assert resolve_friend_name("riya", [JAYMIN, RIYA]) is RIYA


def test_a_first_name_inside_a_longer_name_is_that_friend() -> None:
    assert resolve_friend_name("Jaymin", [JAYMIN, RIYA]) is JAYMIN


def test_a_name_matching_two_friends_resolves_to_neither() -> None:
    friends = [JAYMIN, OTHER_JAYMIN, RIYA]
    assert resolve_friend_name("Jaymin", friends) is None
    assert matching_friends("Jaymin", friends) == [JAYMIN, OTHER_JAYMIN]


def test_an_exact_name_beats_a_longer_name_that_contains_it() -> None:
    plain = Pal("Jaymin")
    assert resolve_friend_name("jaymin", [plain, JAYMIN]) is plain


def test_a_name_nobody_has_matches_nothing() -> None:
    assert matching_friends("Karan", [JAYMIN, RIYA]) == []
    assert resolve_friend_name("Karan", [JAYMIN, RIYA]) is None


def test_a_blank_name_matches_nothing() -> None:
    assert matching_friends("  ", [JAYMIN]) == []
