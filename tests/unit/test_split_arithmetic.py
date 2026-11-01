"""Split arithmetic for shared expenses: pure functions, no database."""

from __future__ import annotations

import pytest

from finance_core.errors import ValidationFailedError
from finance_core.friends.splits import equal_split, exact_split

ME = None  # the recorder is keyed by None, a friend by their id
JAYMIN = "jaymin"
RIYA = "riya"


def test_an_equal_split_of_1000_between_two_gives_each_500() -> None:
    assert equal_split(1000, [ME, JAYMIN], payer=ME) == {ME: 500, JAYMIN: 500}


def test_the_payer_takes_the_leftover_minor_units_of_an_equal_split() -> None:
    shares = equal_split(1000, [ME, JAYMIN, RIYA], payer=ME)
    assert shares == {ME: 334, JAYMIN: 333, RIYA: 333}


def test_a_friend_who_paid_takes_the_leftover_instead_of_the_recorder() -> None:
    shares = equal_split(1000, [ME, JAYMIN, RIYA], payer=RIYA)
    assert shares == {ME: 333, JAYMIN: 333, RIYA: 334}


def test_an_equal_split_always_adds_up_to_the_total() -> None:
    for total in (1, 7, 100, 9_999_999):
        shares = equal_split(max(total, 4), [ME, JAYMIN, RIYA], payer=JAYMIN)
        assert sum(shares.values()) == max(total, 4)


def test_a_total_too_small_to_give_everyone_a_minor_unit_is_refused() -> None:
    with pytest.raises(ValidationFailedError):
        equal_split(2, [ME, JAYMIN, RIYA], payer=ME)


def test_exact_amounts_that_add_up_are_kept_as_given() -> None:
    assert exact_split(1000, {ME: 400, JAYMIN: 600}) == {ME: 400, JAYMIN: 600}


@pytest.mark.parametrize("amounts", [{ME: 400, JAYMIN: 500}, {ME: 400, JAYMIN: 700}])
def test_exact_amounts_that_do_not_add_up_are_a_validation_error(amounts: dict) -> None:  # type: ignore[type-arg]
    with pytest.raises(ValidationFailedError) as caught:
        exact_split(1000, amounts)
    assert caught.value.details["field"] == "split"


def test_an_exact_share_of_zero_is_refused() -> None:
    with pytest.raises(ValidationFailedError):
        exact_split(1000, {ME: 0, JAYMIN: 1000})
