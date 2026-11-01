"""How the offline parser reads settlements, balance questions and shared-expense lists."""

from __future__ import annotations

from datetime import date

import pytest

from finance_core.llm.base import UnderstandRequest
from finance_core.llm.rules import RulesLLMClient
from finance_core.llm.schemas import TurnUnderstanding
from finance_core.llm.settling import read_balance_question, read_paying_back
from finance_core.workflows.reconcile import reconcile

TODAY = date(2026, 10, 24)
FRIENDS = ("Jaymin", "Riya")


async def understand(text: str, accounts: tuple[str, ...] = ("HDFC",)) -> TurnUnderstanding:
    request = UnderstandRequest(
        text=text, today=TODAY, timezone="Asia/Kolkata", base_currency="INR", locale="en-IN",
        categories=[], accounts=accounts, friends=FRIENDS,
    )  # fmt: skip
    return (await RulesLLMClient().understand(request)).understanding


def test_a_friend_paying_me_is_a_settlement_from_that_friend() -> None:
    found = read_paying_back("Jaymin paid me 500", FRIENDS)
    assert found is not None
    assert (found.friend, found.direction, str(found.amount)) == ("Jaymin", "friend_paid_me", "500")


def test_a_friend_paying_me_back_is_the_same_settlement() -> None:
    found = read_paying_back("riya gave me back ₹1,200", FRIENDS)
    assert found is not None
    assert (found.friend, found.direction, str(found.amount)) == ("Riya", "friend_paid_me", "1200")


@pytest.mark.parametrize(
    "text",
    ["paid Jaymin 500", "paid Jaymin back 500", "I paid back Jaymin 500", "paid 500 to Jaymin"],
)
def test_me_paying_a_friend_is_a_settlement_to_that_friend(text: str) -> None:
    found = read_paying_back(text, FRIENDS)
    assert found is not None
    assert (found.friend, found.direction, str(found.amount)) == ("Jaymin", "i_paid_friend", "500")
    assert found.purpose is None


def test_paying_a_friend_for_something_is_not_a_settlement() -> None:
    assert read_paying_back("paid Jaymin 2000 for his old phone", FRIENDS) is None


def test_a_friend_paying_me_for_something_is_still_a_settlement_with_its_purpose() -> None:
    found = read_paying_back("Jaymin paid me 500 for the tickets", FRIENDS)
    assert found is not None and found.purpose == "the tickets"


def test_paying_someone_who_is_not_a_friend_is_not_a_settlement() -> None:
    assert read_paying_back("paid Ramesh 2000", FRIENDS) is None
    assert read_paying_back("paid electricity 1200", FRIENDS) is None


def test_an_ordinary_expense_is_not_a_settlement() -> None:
    assert read_paying_back("spent 350 on dinner", FRIENDS) is None
    assert read_paying_back("me and Jaymin spent 1000 on pizza, split it", FRIENDS) is None


def test_how_much_does_a_friend_owe_me_names_the_friend() -> None:
    assert read_balance_question("How much does Jaymin owe me?", FRIENDS).friend == "Jaymin"  # type: ignore[union-attr]


def test_how_much_do_i_owe_a_friend_names_the_friend() -> None:
    assert read_balance_question("how much do I owe Riya", FRIENDS).friend == "Riya"  # type: ignore[union-attr]


def test_who_owes_me_money_asks_about_every_friend() -> None:
    asked = read_balance_question("who owes me money?", FRIENDS)
    assert asked is not None and asked.friend is None


def test_a_balance_with_a_friend_is_a_balance_question() -> None:
    assert read_balance_question("what's my balance with Jaymin", FRIENDS).friend == "Jaymin"  # type: ignore[union-attr]


def test_other_questions_are_not_balance_questions() -> None:
    assert read_balance_question("how much did I spend this month?", FRIENDS) is None


async def test_the_rules_engine_reads_a_settlement_with_its_account_and_date() -> None:
    result = await understand("Jaymin paid me 500 to HDFC yesterday")
    assert result.intent == "record_settlement"
    spec = result.settlement
    assert spec is not None
    assert (spec.friend, spec.direction, spec.amount, spec.account, spec.date) == (
        "Jaymin", "friend_paid_me", "500", "HDFC", "2026-10-23",
    )  # fmt: skip


async def test_the_rules_engine_reads_a_balance_question() -> None:
    result = await understand("how much does Jaymin owe me?")
    assert result.intent == "balance_question"
    assert result.balance is not None and result.balance.friend == "Jaymin"


async def test_the_rules_engine_keeps_a_purchase_from_a_non_friend_an_expense() -> None:
    result = await understand("paid Ramesh 2000 for his old phone")
    assert result.intent == "record_transactions"


async def test_show_my_shared_expenses_is_a_search_for_shared_expenses() -> None:
    result = await understand("show my shared expenses this month")
    assert result.intent == "search_transactions"
    assert result.search is not None and result.search.shared is True
    assert result.period is not None and result.period.kind == "this_month"


def test_reconcile_takes_the_amount_the_user_wrote_when_the_model_changed_it() -> None:
    from finance_core.llm.schemas import SettlementSpec

    model = TurnUnderstanding(
        intent="record_settlement",
        settlement=SettlementSpec(friend="Jaymin", direction="friend_paid_me", amount="5000"),
    )
    fixed = reconcile(
        model, "Jaymin paid me 500", today=TODAY, locale="en-IN", friend_names=FRIENDS
    )
    assert fixed.settlement is not None and fixed.settlement.amount == "500"


def test_reconcile_adds_the_shared_marker_the_model_missed() -> None:
    from finance_core.llm.schemas import SearchSpec

    model = TurnUnderstanding(intent="search_transactions", search=SearchSpec())
    fixed = reconcile(model, "show my shared expenses", today=TODAY, locale="en-IN")
    assert fixed.search is not None and fixed.search.shared is True
