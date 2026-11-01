"""When "paid X N" is a settlement, when it stays an expense, and how balance replies read."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from finance_core.friends.schemas import BalanceView, FriendView
from finance_core.llm.schemas import SettlementSpec
from finance_core.workflows.friend_replies import (
    compose_balances,
    compose_settlement_saved,
    compose_unclear_settlement,
)
from finance_core.workflows.settling import choose_settlement, expense_from_settlement

NOW = datetime(2026, 10, 24, tzinfo=UTC)


def balance(currency: str, minor: int) -> BalanceView:
    from decimal import Decimal

    symbol = {"INR": "₹", "USD": "$"}[currency]
    return BalanceView(
        currency=currency, amount_minor=minor, amount=Decimal(abs(minor)) / 100,
        formatted=f"{symbol}{abs(minor) / 100:,.2f}",
    )  # fmt: skip


def friend(name: str, *balances: BalanceView) -> FriendView:
    return FriendView(
        id=uuid.uuid4(), name=name, email=None, is_linked=False, invite_status=None,
        balances=list(balances), created_at=NOW, updated_at=NOW,
    )  # fmt: skip


def spec(direction: str, friend_name: str = "Jaymin", **fields: object) -> SettlementSpec:
    return SettlementSpec(
        friend=friend_name,
        direction=direction,
        amount="500",
        **fields,  # type: ignore[arg-type]
    )


def test_a_friend_paying_me_is_a_settlement_even_with_no_balance() -> None:
    jaymin = friend("Jaymin")
    choice = choose_settlement(spec("friend_paid_me"), [jaymin], "INR")
    assert (choice.kind, choice.friend) == ("settle", jaymin)


def test_paying_a_friend_i_owe_is_a_settlement() -> None:
    jaymin = friend("Jaymin", balance("INR", -50000))
    assert choose_settlement(spec("i_paid_friend"), [jaymin], "INR").kind == "settle"


def test_paying_a_friend_who_owes_me_is_still_a_settlement_because_the_balance_is_not_zero() -> (
    None
):
    jaymin = friend("Jaymin", balance("INR", 50000))
    assert choose_settlement(spec("i_paid_friend"), [jaymin], "INR").kind == "settle"


def test_paying_a_friend_with_no_balance_stays_an_expense() -> None:
    assert choose_settlement(spec("i_paid_friend"), [friend("Jaymin")], "INR").kind == "expense"


def test_paying_a_friend_with_a_balance_in_another_currency_stays_an_expense() -> None:
    jaymin = friend("Jaymin", balance("USD", -5000))
    assert choose_settlement(spec("i_paid_friend"), [jaymin], "INR").kind == "expense"


def test_paying_a_friend_in_a_written_currency_checks_that_currency() -> None:
    jaymin = friend("Jaymin", balance("USD", -5000))
    choice = choose_settlement(spec("i_paid_friend", currency="USD"), [jaymin], "INR")
    assert choice.kind == "settle"


def test_paying_for_something_stays_an_expense_even_with_a_balance() -> None:
    jaymin = friend("Jaymin", balance("INR", -50000))
    choice = choose_settlement(spec("i_paid_friend", purpose="his old phone"), [jaymin], "INR")
    assert choice.kind == "expense"


def test_paying_someone_who_is_not_a_friend_stays_an_expense() -> None:
    assert (
        choose_settlement(spec("i_paid_friend", "Ramesh"), [friend("Jaymin")], "INR").kind
        == "expense"
    )


def test_a_stranger_paying_me_asks_to_add_them_first() -> None:
    choice = choose_settlement(spec("friend_paid_me", "Ramesh"), [friend("Jaymin")], "INR")
    assert (choice.kind, choice.reason) == ("ask", "unknown_friend")


def test_two_matching_friends_ask_which_one() -> None:
    friends = [friend("Jaymin Shah"), friend("Jaymin Patel")]
    choice = choose_settlement(spec("friend_paid_me"), friends, "INR")
    assert (choice.kind, choice.reason) == ("ask", "ambiguous_friend")
    assert choice.options == ["Jaymin Shah", "Jaymin Patel"]


def test_a_missing_amount_asks_for_it() -> None:
    choice = choose_settlement(
        SettlementSpec(friend="Jaymin", direction="friend_paid_me"), [friend("Jaymin")], "INR"
    )
    assert (choice.kind, choice.reason) == ("ask", "no_amount")


def test_the_expense_a_settlement_falls_back_to_names_the_friend_as_merchant() -> None:
    tx = expense_from_settlement(
        spec("i_paid_friend", "Ramesh", purpose="his old phone", account="HDFC")
    )
    assert (tx.type, tx.amount, tx.merchant, tx.description, tx.account) == (
        "expense", "500", "Ramesh", "His Old Phone", "HDFC",
    )  # fmt: skip


def test_unclear_settlement_replies_say_what_to_do() -> None:
    assert "Add Ramesh" in compose_unclear_settlement("unknown_friend", "Ramesh", [])
    assert "Jaymin Shah or Jaymin Patel" in compose_unclear_settlement(
        "ambiguous_friend", "Jaymin", ["Jaymin Shah", "Jaymin Patel"]
    )
    assert "how much" in compose_unclear_settlement("no_amount", "Jaymin", []).lower()


def test_a_saved_settlement_says_who_paid_and_what_is_owed_now() -> None:
    text = compose_settlement_saved(
        direction="friend_paid_you", friend="Jaymin", amount_formatted="₹500.00",
        currency="INR", balances=[balance("INR", 30000)], account="HDFC", warning=None,
        unmatched_account=None,
    )  # fmt: skip
    assert text == "Recorded: Jaymin paid you ₹500.00 into HDFC. Jaymin now owes you ₹300.00."


def test_a_saved_settlement_that_clears_the_balance_says_settled_up() -> None:
    text = compose_settlement_saved(
        direction="you_paid_friend", friend="Jaymin", amount_formatted="₹500.00",
        currency="INR", balances=[], account=None, warning=None, unmatched_account=None,
    )  # fmt: skip
    assert text == "Recorded: you paid Jaymin ₹500.00. You and Jaymin are settled up."


def test_a_saved_settlement_repeats_the_services_warning_and_unmatched_account() -> None:
    text = compose_settlement_saved(
        direction="you_paid_friend", friend="Jaymin", amount_formatted="₹500.00",
        currency="INR", balances=[balance("INR", 20000)], account=None,
        warning="That is more than you owed.", unmatched_account="Foo",
    )  # fmt: skip
    assert "Jaymin now owes you ₹200.00." in text
    assert "That is more than you owed." in text
    assert "“Foo”" in text


def test_one_friends_balance_is_worded_per_currency() -> None:
    jaymin = friend("Jaymin", balance("INR", 50000), balance("USD", -2000))
    assert compose_balances([jaymin], asked_about=jaymin.name) == (
        "Jaymin owes you ₹500.00, and you owe Jaymin $20.00."
    )


def test_a_settled_friend_is_reported_as_settled_up() -> None:
    assert compose_balances([friend("Jaymin")], asked_about="Jaymin") == (
        "You and Jaymin are settled up."
    )


def test_all_balances_list_only_friends_with_something_owed() -> None:
    friends = [
        friend("Jaymin", balance("INR", 50000)),
        friend("Riya"),
        friend("Dev", balance("INR", -1000)),
    ]
    assert compose_balances(friends, asked_about=None) == (
        "Jaymin owes you ₹500.00. You owe Dev ₹10.00."
    )


def test_nobody_owing_anything_says_everyone_is_settled_up() -> None:
    assert compose_balances([friend("Riya")], asked_about=None) == (
        "Nobody owes anything: you are settled up with everyone."
    )
