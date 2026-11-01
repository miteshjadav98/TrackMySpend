"""Merchant rules end to end: saves teach them, and the chat files the next one by them."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from finance_core.clock import FixedClock
from finance_core.errors import ConflictError
from finance_core.transactions.schemas import TransactionCreate
from finance_core.transactions.service import TransactionService
from finance_core.users.context import UserContext
from tests.conftest import NOW, new_conversation, register, say

TX = "/api/v1/transactions"
RULES = "/api/v1/merchant-rules"


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


async def _rules(client: httpx.AsyncClient, **params: Any) -> list[dict[str, Any]]:
    """The merchant rules Settings shows, read through the API."""
    response = await client.get(RULES, params=params)
    assert response.status_code == 200, response.text
    return response.json()["items"]  # type: ignore[no-any-return]


async def _rule(client: httpx.AsyncClient, merchant: str) -> dict[str, Any] | None:
    """This user's expense rule for exactly this merchant, or None."""
    found = await _rules(client, type="expense", q=merchant)
    return next((rule for rule in found if rule["merchant"] == merchant), None)


async def _teach(
    client: httpx.AsyncClient, *, merchant: str, category_id: str, type: str = "expense"
) -> None:
    """Save a transaction through the API, which teaches its merchant rule."""
    body = {"type": type, "amount": "100", "merchant": merchant, "categoryId": category_id}
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


async def test_a_retried_save_does_not_count_as_another_use(client: httpx.AsyncClient) -> None:
    await register(client)
    food = await _category_id(client, "food")
    retry = {"Idempotency-Key": "swiggy-order-1"}
    body = {"type": "expense", "amount": "300", "merchant": "Swiggy", "categoryId": food}
    assert (await client.post(TX, json=body, headers=retry)).status_code == 201
    assert (await client.post(TX, json=body, headers=retry)).status_code == 200  # a replay
    assert (await _rule(client, "Swiggy") or {}).get("timesUsed") == 1

    assert (await client.post(TX, json=body)).status_code == 201
    assert (await _rule(client, "Swiggy") or {}).get("timesUsed") == 2


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

    assert await _rule(client, "Swiggy") is None
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


# ---------------------------------------------------------------------------------------
# Settings → Merchant rules: list, change and forget them through the API
# ---------------------------------------------------------------------------------------


@pytest.fixture
def moving_clock(clock: FixedClock) -> Iterator[FixedClock]:
    """The app's clock, which this test may move forward; it goes back to NOW afterwards."""
    yield clock
    clock.set(NOW)


async def test_rules_are_listed_most_recently_used_first(
    client: httpx.AsyncClient, moving_clock: FixedClock
) -> None:
    await register(client)
    food = await _category_id(client, "food")
    await _teach(client, merchant="Swiggy", category_id=food)
    moving_clock.set(NOW + timedelta(minutes=1))
    await _teach(client, merchant="Zomato", category_id=food)
    moving_clock.set(NOW + timedelta(minutes=2))
    await _teach(client, merchant="Uber", category_id=await _category_id(client, "transport"))
    moving_clock.set(NOW + timedelta(minutes=3))
    await _teach(client, merchant="swiggy!", category_id=food)

    rules = await _rules(client)

    assert [rule["merchant"] for rule in rules] == ["swiggy!", "Uber", "Zomato"]
    swiggy = rules[0]
    assert swiggy["type"] == "expense"
    assert swiggy["category"]["name"] == "Food & Dining"
    assert swiggy["timesUsed"] == 2
    assert datetime.fromisoformat(swiggy["lastUsedAt"]) == NOW + timedelta(minutes=3)


async def test_rules_can_be_filtered_by_type_and_searched_by_merchant(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    food = await _category_id(client, "food")
    await _teach(client, merchant="Swiggy", category_id=food)
    await _teach(client, merchant="Swiggy Instamart", category_id=food)
    await _teach(client, merchant="Amazon", category_id=await _category_id(client, "shopping"))
    refund = await _category_id(client, "refund")
    await _teach(client, merchant="Amazon", category_id=refund, type="income")

    swiggy = await _rules(client, q="swig")
    assert sorted(rule["merchant"] for rule in swiggy) == ["Swiggy", "Swiggy Instamart"]
    income = await _rules(client, type="income")
    assert [(rule["merchant"], rule["category"]["name"]) for rule in income] == [
        ("Amazon", "Refunds & Cashback")
    ]
    # Searched the way merchants are matched: case and punctuation don't matter.
    amazon = await _rules(client, q="AMAZON!", type="expense")
    assert [(rule["merchant"], rule["type"]) for rule in amazon] == [("Amazon", "expense")]


async def test_rules_are_listed_a_page_at_a_time(
    client: httpx.AsyncClient, moving_clock: FixedClock
) -> None:
    await register(client)
    food = await _category_id(client, "food")
    for minute, merchant in enumerate(["Swiggy", "Zomato", "Dominos"]):
        moving_clock.set(NOW + timedelta(minutes=minute))
        await _teach(client, merchant=merchant, category_id=food)

    first = (await client.get(RULES, params={"limit": 2})).json()
    assert [rule["merchant"] for rule in first["items"]] == ["Dominos", "Zomato"]
    rest = (await client.get(RULES, params={"limit": 2, "cursor": first["nextCursor"]})).json()
    assert [rule["merchant"] for rule in rest["items"]] == ["Swiggy"]
    assert rest["nextCursor"] is None

    broken = await client.get(RULES, params={"cursor": "not-a-cursor"})
    assert broken.status_code == 422


async def test_a_changed_rule_files_the_merchants_next_transaction(
    client: httpx.AsyncClient, chat: str
) -> None:
    await say(client, chat, "swiggy 300")
    [swiggy] = await _rules(client, q="swiggy")
    office_meals = await _create_category(client, "Office meals")

    changed = await client.patch(f"{RULES}/{swiggy['id']}", json={"categoryId": office_meals})
    assert changed.status_code == 200, changed.text
    assert changed.json()["category"]["name"] == "Office meals"
    assert changed.json()["timesUsed"] == 1  # changing a rule is not using it

    result = await say(client, chat, "swiggy 250")
    assert _saved(result)["category"]["name"] == "Office meals"
    assert "Filed under Office meals, as before for Swiggy." in _reply(result)


async def test_a_rule_only_changes_to_a_real_category_of_its_own_type(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    await _teach(client, merchant="Swiggy", category_id=await _category_id(client, "food"))
    [swiggy] = await _rules(client)
    path = f"{RULES}/{swiggy['id']}"

    income = await client.patch(path, json={"categoryId": await _category_id(client, "salary")})
    assert income.status_code == 422
    assert income.json()["error"]["details"]["field"] == "categoryId"
    unknown = await client.patch(path, json={"categoryId": str(uuid.uuid4())})
    assert unknown.status_code == 404
    # "Other" means "I don't know", which never becomes a rule.
    other = await client.patch(path, json={"categoryId": await _category_id(client, "other")})
    assert other.status_code == 422
    assert other.json()["error"]["details"]["field"] == "categoryId"

    [unchanged] = await _rules(client)
    assert unchanged["category"]["name"] == "Food & Dining"


async def test_a_forgotten_rule_is_learned_again_from_the_next_save(
    client: httpx.AsyncClient, chat: str
) -> None:
    office_meals = await _create_category(client, "Office meals")
    await _teach(client, merchant="Swiggy", category_id=office_meals)
    [swiggy] = await _rules(client)

    forgotten = await client.delete(f"{RULES}/{swiggy['id']}")
    assert forgotten.status_code == 204
    assert await _rules(client) == []

    result = await say(client, chat, "swiggy 250")
    assert _saved(result)["category"]["name"] == "Food & Dining"  # the model's guess
    assert "as before" not in _reply(result)
    [relearned] = await _rules(client)
    assert (relearned["category"]["name"], relearned["timesUsed"]) == ("Food & Dining", 1)


async def test_changing_and_forgetting_a_rule_are_audited(
    app: Any, client: httpx.AsyncClient
) -> None:
    me = await register(client)
    food, groceries = await _category_id(client, "food"), await _category_id(client, "groceries")
    await _teach(client, merchant="Swiggy", category_id=food)
    [swiggy] = await _rules(client)

    await client.patch(f"{RULES}/{swiggy['id']}", json={"categoryId": groceries})
    await client.delete(f"{RULES}/{swiggy['id']}")

    async with app.state.container.session_factory() as session:
        events = (
            await session.scalars(
                select(AuditEvent)
                .where(AuditEvent.user_id == me["user"]["id"], AuditEvent.entity_id == swiggy["id"])
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
    assert [event.action for event in events] == [
        "merchant_rule.changed",
        "merchant_rule.forgotten",
    ]
    changed, forgotten = events
    assert changed.data == {
        "merchant": "Swiggy",
        "type": "expense",
        "categoryId": [food, groceries],
    }
    assert forgotten.data == {"merchant": "Swiggy", "type": "expense", "categoryId": groceries}
