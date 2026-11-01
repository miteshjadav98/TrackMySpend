"""Shared expenses recorded through the chat: who is asked what, and what the save card shows."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from finance_core.errors import NotFoundError
from finance_core.friends.shared_expenses import SharedExpenseService
from finance_core.llm.base import ReplyRequest, UnderstandRequest, UnderstandResult
from finance_core.llm.schemas import ExtractedTransaction, TurnUnderstanding
from tests.conftest import new_conversation, register, say

FRIENDS = "/api/v1/friends"
SHARED = "/api/v1/shared-expenses"
ACCOUNTS = "/api/v1/accounts"
SUMMARY = "/api/v1/reports/summary"
TX = "/api/v1/transactions"


@pytest.fixture
async def chat(client: httpx.AsyncClient) -> str:
    await register(client)
    return await new_conversation(client)


async def add_friend(client: httpx.AsyncClient, name: str, email: str | None = None) -> str:
    created = await client.post(FRIENDS, json={"name": name, "email": email})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def saved_card(result: dict[str, Any]) -> dict[str, Any]:
    assert result["pendingInteraction"] is None, result["pendingInteraction"]
    card = result["assistantMessage"]["ui"][0]
    assert card["type"] == "transactions_saved", result["assistantMessage"]
    return card  # type: ignore[no-any-return]


def only_shared(result: dict[str, Any]) -> dict[str, Any]:
    [shared] = saved_card(result)["shared"]
    return shared  # type: ignore[no-any-return]


def shares_of(shared: dict[str, Any]) -> dict[str, int]:
    return {share["name"]: share["amountMinor"] for share in shared["shares"]}


def answer(question: dict[str, Any], value: str) -> dict[str, Any]:
    return {"interactionId": question["id"], "action": "submit", "value": value}


async def test_me_and_a_friend_splitting_a_bill_saves_an_equal_shared_expense(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")

    result = await say(client, chat, "me and Jaymin spent 1000 on pizza, split it")

    shared = only_shared(result)
    assert (shared["totalMinor"], shared["paidByYou"]) == (100000, True)
    assert shares_of(shared) == {"You": 50000, "Jaymin": 50000}
    [mine] = saved_card(result)["transactions"]
    assert (mine["amountMinor"], mine["category"]["slug"]) == (50000, "food")
    assert mine["sharedExpenseId"] == shared["id"]
    assert result["assistantMessage"]["content"] == (
        "Saved ₹1,000.00 shared expense for Pizza under Food & Dining today. "
        "You paid. Shares: You ₹500.00, Jaymin ₹500.00."
    )


async def test_only_my_share_counts_in_my_spending(client: httpx.AsyncClient, chat: str) -> None:
    await add_friend(client, "Jaymin")

    await say(client, chat, "me and Jaymin spent 1000 on pizza, split it")

    summary = (await client.get(SUMMARY, params={"period": "this_month"})).json()
    assert summary["currencies"][0]["expense"]["amountMinor"] == 50000


async def test_a_friend_paying_is_named_as_the_payer(client: httpx.AsyncClient, chat: str) -> None:
    await add_friend(client, "Jaymin")

    result = await say(client, chat, "Jaymin paid 1000 for pizza, split it")

    shared = only_shared(result)
    assert (shared["payer"]["name"], shared["paidByYou"]) == ("Jaymin", False)
    assert shares_of(shared) == {"You": 50000, "Jaymin": 50000}
    assert "Jaymin paid." in result["assistantMessage"]["content"]


async def test_a_group_bill_with_two_friends_splits_three_ways(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")
    await add_friend(client, "Riya")

    shared = only_shared(await say(client, chat, "me, Jaymin and Riya spent 1000 on cab, split it"))

    # The payer takes the leftover paisa, so the shares still add up to the bill.
    assert shares_of(shared) == {"You": 33334, "Jaymin": 33333, "Riya": 33333}


async def test_exact_amounts_give_each_person_what_they_said(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")

    shared = only_shared(
        await say(client, chat, "dinner 1000 with Jaymin, I had 400 and he had 600")
    )

    assert shares_of(shared) == {"You": 40000, "Jaymin": 60000}


async def test_exact_amounts_that_do_not_add_up_are_asked_again_with_a_notice(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")

    question = (await say(client, chat, "dinner 1000 with Jaymin, I had 400 and he had 500"))[
        "pendingInteraction"
    ]
    assert question["field"] == "split"
    assert question["message"].startswith("Those add up to ₹900.00, but the total is ₹1,000.00.")

    shared = only_shared(await say(client, chat, "I had 400, Jaymin 600"))
    assert shares_of(shared) == {"You": 40000, "Jaymin": 60000}


async def test_an_unknown_name_offers_to_add_a_new_friend_and_adds_them_at_save(
    client: httpx.AsyncClient, chat: str
) -> None:
    question = (await say(client, chat, "me and Jaymin spent 1000 on pizza, split it"))[
        "pendingInteraction"
    ]
    assert question["message"] == "Add Jaymin as a new friend?"
    assert (await client.get(FRIENDS)).json() == []  # nothing is added before the user agrees

    result = await say(client, chat, answer=answer(question, "add"))

    assert shares_of(only_shared(result)) == {"You": 50000, "Jaymin": 50000}
    assert [f["name"] for f in (await client.get(FRIENDS)).json()] == ["Jaymin"]
    assert "added Jaymin to your friends" in result["assistantMessage"]["content"]


async def test_two_friends_with_the_same_name_ask_which_one_and_show_emails(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin Shah", "jaymin.shah@example.com")
    patel = await add_friend(client, "Jaymin Patel")

    question = (await say(client, chat, "me and Jaymin spent 1000 on pizza, split it"))[
        "pendingInteraction"
    ]
    assert question["message"] == "Which Jaymin do you mean?"
    assert [(o["label"], o["description"]) for o in question["options"]] == [
        ("Jaymin Patel", None),
        ("Jaymin Shah", "jaymin.shah@example.com"),
    ]

    shared = only_shared(await say(client, chat, answer=answer(question, patel)))
    assert "Jaymin Patel" in shares_of(shared)


async def test_a_friend_who_paid_with_two_others_asks_the_user_to_narrow_it_down(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")
    await add_friend(client, "Riya")

    question = (
        await say(client, chat, "Jaymin paid 1500 for cab, split with me, Jaymin and Riya")
    )["pendingInteraction"]
    assert question["field"] == "payer"
    assert "only be split between you and the friend who paid" in question["message"]

    shared = only_shared(await say(client, chat, answer=answer(question, "only_payer")))
    assert (shared["payer"]["name"], shares_of(shared)) == (
        "Jaymin",
        {"You": 75000, "Jaymin": 75000},
    )


async def test_paid_from_an_account_still_tags_my_share(
    client: httpx.AsyncClient, chat: str
) -> None:
    hdfc = (await client.post(ACCOUNTS, json={"name": "HDFC", "kind": "bank"})).json()
    await add_friend(client, "Jaymin")

    result = await say(client, chat, "me and Jaymin spent 1000 on pizza from HDFC, split it")

    [mine] = saved_card(result)["transactions"]
    assert mine["account"]["id"] == hdfc["id"]
    assert "from HDFC" in result["assistantMessage"]["content"]


async def test_the_category_picked_in_a_question_files_my_share(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")

    question = (await say(client, chat, "me and Jaymin spent 1000, split it"))["pendingInteraction"]
    assert question["field"] == "category"

    result = await say(client, chat, answer=answer(question, "entertainment"))
    [mine] = saved_card(result)["transactions"]
    assert (mine["amountMinor"], mine["category"]["slug"]) == (50000, "entertainment")


async def test_a_retried_message_never_records_the_shared_expense_twice(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")
    message_id = str(uuid.uuid4())

    await say(
        client, chat, "me and Jaymin spent 1000 on pizza, split it", client_message_id=message_id
    )
    again = await say(
        client, chat, "me and Jaymin spent 1000 on pizza, split it", client_message_id=message_id
    )

    assert again["replayed"] is True
    assert len((await client.get(SHARED)).json()) == 1
    assert len((await client.get(TX)).json()["items"]) == 1


async def test_an_expense_with_a_friend_but_no_split_stays_an_ordinary_expense(
    client: httpx.AsyncClient, chat: str
) -> None:
    await add_friend(client, "Jaymin")

    result = await say(client, chat, "coffee with Jaymin 200")

    assert saved_card(result)["shared"] == []
    assert (await client.get(SHARED)).json() == []


class _ReadsCoffeeAndAPizzaSplit:
    """A model that reads one message as an ordinary coffee plus a pizza shared with Jaymin."""

    name = "scripted"

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        understanding = TurnUnderstanding(
            intent="record_transactions",
            transactions=[
                ExtractedTransaction(
                    type="expense", amount="200", category="food", description="Coffee"
                ),
                ExtractedTransaction(
                    type="expense",
                    amount="1000",
                    category="food",
                    description="Pizza",
                    participants=["Jaymin"],
                    split="equal",
                ),
            ],
        )
        return UnderstandResult(understanding=understanding, source="scripted", latency_ms=1)

    async def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]:
        yield ""


async def test_a_mixed_message_saves_the_ordinary_and_the_shared_expense_together(
    client: httpx.AsyncClient, chat: str, llm: Any
) -> None:
    await add_friend(client, "Jaymin")
    llm.delegate = _ReadsCoffeeAndAPizzaSplit()

    result = await say(client, chat, "coffee 200 and pizza 1000")

    card = saved_card(result)
    assert [t["description"] for t in card["transactions"]] == ["Coffee", "Pizza"]
    assert len(card["shared"]) == 1
    assert len((await client.get(TX)).json()["items"]) == 2


async def test_a_failed_shared_expense_saves_nothing_from_that_message(
    client: httpx.AsyncClient, chat: str, llm: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    await add_friend(client, "Jaymin")
    llm.delegate = _ReadsCoffeeAndAPizzaSplit()

    async def fails_midway(*args: Any, **kwargs: Any) -> None:
        raise NotFoundError("Friend not found")  # after the expense row was already written

    monkeypatch.setattr(SharedExpenseService, "_create_share_transactions", fails_midway)

    await say(client, chat, "coffee 200 and pizza 1000")

    assert (await client.get(TX)).json()["items"] == []
    assert (await client.get(SHARED)).json() == []
