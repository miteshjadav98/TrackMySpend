"""Settlements, balance questions and the shared-expense list, asked in chat."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from finance_core.llm.base import ReplyRequest, UnderstandRequest, UnderstandResult
from finance_core.llm.schemas import SettlementSpec, TurnUnderstanding
from tests.conftest import new_conversation, register, say
from tests.integration.test_settlements import add_friend, balances_of, share

SETTLEMENTS = "/api/v1/settlements"
ACCOUNTS = "/api/v1/accounts"
TX = "/api/v1/transactions"
SUMMARY = "/api/v1/reports/summary"


class _ReadsASettlement:
    """A model that returns one fixed settlement, as the live model would for an account the
    user does not have."""

    name = "scripted"

    def __init__(self, spec: SettlementSpec) -> None:
        self._understanding = TurnUnderstanding(intent="record_settlement", settlement=spec)

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        return UnderstandResult(understanding=self._understanding, source="scripted", latency_ms=1)

    async def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]:
        yield ""


@pytest.fixture
async def chat(client: httpx.AsyncClient) -> str:
    await register(client)
    return await new_conversation(client)


def reply(result: dict[str, Any]) -> str:
    return result["assistantMessage"]["content"]  # type: ignore[no-any-return]


async def test_a_friend_paying_me_back_records_a_settlement_and_clears_the_balance(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")  # Jaymin owes me 500

    result = await say(client, chat, "Jaymin paid me 500")

    assert reply(result) == "Recorded: Jaymin paid you ₹500.00. You and Jaymin are settled up."
    assert await balances_of(client, jaymin) == {}
    [settlement] = (await client.get(SETTLEMENTS)).json()
    assert (settlement["direction"], settlement["amountMinor"]) == ("friend_paid_you", 50000)


async def test_a_settlement_is_neither_spending_nor_income(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    before = (await client.get(SUMMARY, params={"period": "this_month"})).json()
    transactions_before = (await client.get(TX)).json()["items"]

    await say(client, chat, "Jaymin paid me 500")

    assert (await client.get(SUMMARY, params={"period": "this_month"})).json() == before
    assert (await client.get(TX)).json()["items"] == transactions_before


async def test_paying_a_friend_i_owe_records_a_settlement_from_me(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000", friend_paid=True)  # I owe Jaymin 500

    result = await say(client, chat, "paid Jaymin 300")

    assert reply(result) == "Recorded: you paid Jaymin ₹300.00. You now owe Jaymin ₹200.00."
    assert await balances_of(client, jaymin) == {"INR": -20000}


async def test_a_settlement_can_be_tagged_with_the_account_the_money_went_into(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    account = (await client.post(ACCOUNTS, json={"name": "HDFC", "kind": "bank"})).json()

    result = await say(client, chat, "Jaymin paid me 500 to HDFC")

    assert "into HDFC" in reply(result)
    [settlement] = (await client.get(SETTLEMENTS)).json()
    assert settlement["account"]["id"] == account["id"]


async def test_an_account_that_matches_nothing_is_dropped_and_said_so(
    client: httpx.AsyncClient, chat: str, llm: Any
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    llm.delegate = _ReadsASettlement(
        SettlementSpec(friend="Jaymin", direction="friend_paid_me", amount="500", account="Nowhere")
    )

    result = await say(client, chat, "Jaymin paid me 500 to Nowhere")

    assert "couldn't match “Nowhere”" in reply(result)
    [settlement] = (await client.get(SETTLEMENTS)).json()
    assert settlement["account"] is None


async def test_paying_a_friend_with_nothing_owed_stays_an_expense(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")

    result = await say(client, chat, "paid Jaymin 500")

    assert (await client.get(SETTLEMENTS)).json() == []
    assert result["pendingInteraction"]["field"] == "category"  # asked like any expense


async def test_paying_a_friend_for_something_stays_an_expense_even_with_a_balance(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000", friend_paid=True)

    await say(client, chat, "paid Jaymin 2000 for his old phone")

    assert (await client.get(SETTLEMENTS)).json() == []
    assert await balances_of(client, jaymin) == {"INR": -50000}


async def test_paying_someone_who_is_not_a_friend_stays_an_expense(
    client: httpx.AsyncClient, chat: str
) -> None:
    result = await say(client, chat, "paid Ramesh 2000 for his old phone")

    assert (await client.get(SETTLEMENTS)).json() == []
    assert result["pendingInteraction"]["field"] == "category"


async def test_someone_who_is_not_a_friend_paying_me_asks_to_add_them_first(
    client: httpx.AsyncClient, chat: str
) -> None:
    result = await say(client, chat, "Ramesh paid me 500")

    assert reply(result).startswith("I don't have a friend called Ramesh.")
    assert (await client.get(SETTLEMENTS)).json() == []


async def test_two_friends_with_the_same_first_name_ask_which_one(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin Shah")
    await add_friend(client, "Jaymin Patel")

    result = await say(client, chat, "Jaymin paid me 500")

    assert "Jaymin Patel or Jaymin Shah" in reply(result)  # friends list order
    assert (await client.get(SETTLEMENTS)).json() == []


async def test_a_retried_message_never_records_the_settlement_twice(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    message_id = str(uuid.uuid4())

    await say(client, chat, "Jaymin paid me 200", client_message_id=message_id)
    again = await say(client, chat, "Jaymin paid me 200", client_message_id=message_id)

    assert again["replayed"] is True
    assert len((await client.get(SETTLEMENTS)).json()) == 1


async def test_a_friend_who_owes_me_is_answered_from_the_balance(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")

    result = await say(client, chat, "How much does Jaymin owe me?")

    assert reply(result) == "Jaymin owes you ₹500.00."


async def test_balances_stay_separate_per_currency(client: httpx.AsyncClient, chat: str) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    await share(client, jaymin, "40", friend_paid=True, currency="USD")

    result = await say(client, chat, "how much does Jaymin owe me")

    assert reply(result) == "Jaymin owes you ₹500.00, and you owe Jaymin $20.00."


async def test_who_owes_me_money_lists_every_friend_with_a_balance(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    dev = await add_friend(client, "Dev")
    await add_friend(client, "Riya")
    await share(client, jaymin, "1000")
    await share(client, dev, "200", friend_paid=True)

    result = await say(client, chat, "who owes me money?")

    assert reply(result) == "You owe Dev ₹100.00. Jaymin owes you ₹500.00."  # by name


async def test_when_nobody_owes_anything_the_answer_says_so(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")

    result = await say(client, chat, "who owes me money?")

    assert reply(result) == "Nobody owes anything: you are settled up with everyone."


async def test_a_balance_question_about_an_unknown_name_says_there_is_no_such_friend(
    client: httpx.AsyncClient, chat: str
) -> None:
    result = await say(client, chat, "how much does Ramesh owe me?")

    assert reply(result).startswith("I don't have a friend called Ramesh.")


async def test_show_my_shared_expenses_lists_only_the_shared_ones(
    client: httpx.AsyncClient, chat: str
) -> None:
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000", on="2026-10-20")
    await say(client, chat, "spent 120 on coffee")

    result = await say(client, chat, "show my shared expenses this month")

    card = result["assistantMessage"]["ui"][0]
    assert card["type"] == "transaction_list"
    assert card["title"] == "Recent shared expenses"
    [mine] = card["transactions"]
    assert (mine["amountMinor"], mine["sharedExpenseId"] is not None) == (50000, True)
