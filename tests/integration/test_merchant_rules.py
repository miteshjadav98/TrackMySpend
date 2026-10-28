"""Merchant rules end to end: saves teach them, and the chat files the next one by them."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest

from finance_core.errors import ConflictError
from finance_core.merchants.models import MerchantRule
from finance_core.merchants.service import MerchantRuleService
from finance_core.transactions.schemas import TransactionCreate
from finance_core.transactions.service import TransactionService
from finance_core.users.context import UserContext
from tests.conftest import new_conversation, register, say

TX = "/api/v1/transactions"


def _saved(result: dict[str, Any]) -> dict[str, Any]:
    assert result["pendingInteraction"] is None, result["pendingInteraction"]
    card = result["assistantMessage"]["ui"][0]
    assert card["type"] == "transactions_saved", result["assistantMessage"]
    [transaction] = card["transactions"]
    return transaction  # type: ignore[no-any-return]


def _reply(result: dict[str, Any]) -> str:
    return result["assistantMessage"]["content"]  # type: ignore[no-any-return]


async def _create_category(client: httpx.AsyncClient, name: str) -> str:
    created = await client.post("/api/v1/categories", json={"name": name, "kind": "expense"})
    assert created.status_code == 201, created.text
    return created.json()["id"]  # type: ignore[no-any-return]


async def _category_id(client: httpx.AsyncClient, slug: str) -> str:
    categories = (await client.get("/api/v1/categories")).json()
    return next(c["id"] for c in categories if c["slug"] == slug)  # type: ignore[no-any-return]


async def _rule(app: Any, me: dict[str, Any], merchant: str) -> MerchantRule | None:
    """Read an expense rule through the merchants service (no REST view until ticket 05)."""
    container = app.state.container
    async with container.session_factory() as session:
        return await MerchantRuleService(session, clock=container.clock).find(
            uuid.UUID(me["user"]["id"]), type="expense", merchant=merchant
        )


async def _teach(client: httpx.AsyncClient, *, merchant: str, category_id: str) -> None:
    """Save an expense through the API, which teaches its merchant rule."""
    body = {"type": "expense", "amount": "100", "merchant": merchant, "categoryId": category_id}
    created = await client.post(TX, json=body)
    assert created.status_code == 201, created.text


@pytest.fixture
async def chat(client: httpx.AsyncClient) -> str:
    await register(client)
    return await new_conversation(client)


async def test_a_guessed_category_is_learned_for_the_merchant(
    client: httpx.AsyncClient, chat: str
) -> None:
    first = await say(client, chat, "swiggy 300")
    assert _saved(first)["category"]["name"] == "Food & Dining"
    assert "as before" not in _reply(first)

    second = await say(client, chat, "swiggy 250")
    assert _saved(second)["category"]["name"] == "Food & Dining"
    assert "Filed under Food & Dining, as before for Swiggy." in _reply(second)


async def test_changing_the_category_on_the_transactions_page_updates_the_rule(
    client: httpx.AsyncClient, chat: str
) -> None:
    swiggy = _saved(await say(client, chat, "swiggy 300"))
    office_meals = await _create_category(client, "Office meals")
    edited = await client.patch(
        f"{TX}/{swiggy['id']}", json={"version": swiggy["version"], "categoryId": office_meals}
    )
    assert edited.status_code == 200

    result = await say(client, chat, "swiggy 250")
    assert _saved(result)["category"]["name"] == "Office meals"
    assert "Filed under Office meals, as before for Swiggy." in _reply(result)


async def test_a_category_named_in_the_message_wins_and_becomes_the_rule(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _teach(
        client, merchant="Swiggy", category_id=await _create_category(client, "Office meals")
    )

    named = await say(client, chat, "swiggy 400 groceries")
    assert _saved(named)["category"]["name"] == "Groceries"
    assert "as before" not in _reply(named)

    after = await say(client, chat, "swiggy 100")
    assert _saved(after)["category"]["name"] == "Groceries"
    assert "Filed under Groceries, as before for Swiggy." in _reply(after)


async def test_a_category_picked_in_a_clarification_is_learned(
    client: httpx.AsyncClient, chat: str
) -> None:
    question = (await say(client, chat, "spent 500 at Ramesh Stores"))["pendingInteraction"]
    assert question["field"] == "category"
    picked = await say(
        client,
        chat,
        answer={"interactionId": question["id"], "action": "submit", "value": "groceries"},
    )
    assert _saved(picked)["category"]["name"] == "Groceries"

    next_time = await say(client, chat, "spent 300 at Ramesh Stores")
    assert _saved(next_time)["category"]["name"] == "Groceries"  # no question this time
    assert "Filed under Groceries, as before for Ramesh Stores." in _reply(next_time)


async def test_changing_the_merchant_on_the_transactions_page_teaches_a_rule(
    client: httpx.AsyncClient, chat: str
) -> None:
    groceries = await _category_id(client, "groceries")
    created = await client.post(
        TX, json={"type": "expense", "amount": "90", "categoryId": groceries}
    )
    tx = created.json()
    edited = await client.patch(
        f"{TX}/{tx['id']}", json={"version": tx["version"], "merchant": "Ramesh Stores"}
    )
    assert edited.status_code == 200

    result = await say(client, chat, "spent 300 at Ramesh Stores")
    assert _saved(result)["category"]["name"] == "Groceries"


async def test_merchant_names_match_whatever_the_case_punctuation_or_spacing(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _teach(
        client, merchant="  RAMESH   STORES. ", category_id=await _category_id(client, "groceries")
    )
    await _teach(
        client, merchant="SWIGGY!", category_id=await _create_category(client, "Office meals")
    )

    ramesh = await say(client, chat, "spent 300 at Ramesh Stores")
    assert _saved(ramesh)["category"]["name"] == "Groceries"
    swiggy = await say(client, chat, "swiggy 250")
    assert _saved(swiggy)["category"]["name"] == "Office meals"


async def test_expense_and_income_rules_are_kept_apart(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _teach(client, merchant="Amazon", category_id=await _create_category(client, "Gadgets"))

    # The expense rule says nothing about money coming in from Amazon.
    refund = (await say(client, chat, "received 500 from Amazon"))["pendingInteraction"]
    assert refund["field"] == "category"
    await say(
        client, chat, answer={"interactionId": refund["id"], "action": "submit", "value": "refund"}
    )

    expense = await say(client, chat, "spent 2000 at Amazon")
    assert _saved(expense)["category"]["name"] == "Gadgets"
    income = await say(client, chat, "received 300 from Amazon")
    assert _saved(income)["category"]["name"] == "Refunds & Cashback"
    assert "as before for Amazon" in _reply(income)


async def test_nothing_is_learned_without_a_merchant_or_from_a_fallback_category(
    client: httpx.AsyncClient, chat: str
) -> None:
    office_meals = await _create_category(client, "Office meals")
    no_merchant = {
        "type": "expense",
        "amount": "80",
        "description": "Swiggy",
        "categoryId": office_meals,
    }
    assert (await client.post(TX, json=no_merchant)).status_code == 201
    await _teach(client, merchant="Swiggy", category_id=await _category_id(client, "other"))

    swiggy = await say(client, chat, "swiggy 250")
    assert _saved(swiggy)["category"]["name"] == "Food & Dining"  # still the model's guess
    assert "as before" not in _reply(swiggy)


async def test_a_skipped_category_question_teaches_nothing(
    client: httpx.AsyncClient, chat: str
) -> None:
    question = (await say(client, chat, "spent 75 at Ramesh Stores"))["pendingInteraction"]
    skipped = await say(client, chat, answer={"interactionId": question["id"], "action": "skip"})
    assert _saved(skipped)["category"]["name"] == "Other"

    again = (await say(client, chat, "spent 80 at Ramesh Stores"))["pendingInteraction"]
    assert again is not None and again["field"] == "category"


async def test_a_retried_save_does_not_count_as_another_use(
    app: Any, client: httpx.AsyncClient
) -> None:
    me = await register(client)
    food = await _category_id(client, "food")
    retry = {"Idempotency-Key": "swiggy-order-1"}
    body = {"type": "expense", "amount": "300", "merchant": "Swiggy", "categoryId": food}
    assert (await client.post(TX, json=body, headers=retry)).status_code == 201
    assert (await client.post(TX, json=body, headers=retry)).status_code == 200  # a replay
    assert (await _rule(app, me, "Swiggy")).times_used == 1

    assert (await client.post(TX, json=body)).status_code == 201
    assert (await _rule(app, me, "Swiggy")).times_used == 2


async def test_a_save_that_rolls_back_leaves_no_rule_behind(
    app: Any, client: httpx.AsyncClient
) -> None:
    me = await register(client)
    office_meals = uuid.UUID(await _create_category(client, "Office meals"))
    used = {"Idempotency-Key": "order-0001"}
    assert (
        await client.post(TX, json={"type": "expense", "amount": "50"}, headers=used)
    ).status_code == 201

    # No HTTP path fails a save after learning, so drive the service with a batch whose
    # second item reuses that key for different data: the whole batch rolls back.
    ctx = UserContext(uuid.UUID(me["user"]["id"]), "INR", "Asia/Kolkata", "en-IN")
    container = app.state.container
    async with container.session_factory() as session:
        transactions = TransactionService(session, clock=container.clock)
        swiggy = await transactions.resolve(
            ctx,
            TransactionCreate(
                type="expense", amount=Decimal(300), merchant="Swiggy", category_id=office_meals
            ),
        )
        clash = await transactions.resolve(
            ctx, TransactionCreate(type="expense", amount=Decimal(999))
        )
        with pytest.raises(ConflictError):
            await transactions.create_resolved(
                ctx,
                [(swiggy, None), (clash, "api:order-0001")],
                source="api",
                strict_idempotency=True,
            )

    assert await _rule(app, me, "Swiggy") is None
    assert len((await client.get(TX)).json()["items"]) == 1


async def test_another_users_rules_never_file_my_transactions(make_client: Any) -> None:
    alice, bob = make_client(), make_client()
    await register(alice)
    await register(bob)
    await _teach(
        alice, merchant="Swiggy", category_id=await _create_category(alice, "Office meals")
    )

    result = await say(bob, await new_conversation(bob), "swiggy 250")
    assert _saved(result)["category"]["name"] == "Food & Dining"
    assert "as before" not in _reply(result)
