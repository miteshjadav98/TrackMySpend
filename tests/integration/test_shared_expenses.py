"""Shared expenses recorded by the user: the split, the user's own share, edits and deletes."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from tests.conftest import register

SHARED = "/api/v1/shared-expenses"
FRIENDS = "/api/v1/friends"
TX = "/api/v1/transactions"
SUMMARY = "/api/v1/reports/summary"
RULES = "/api/v1/merchant-rules"
NO_SUCH_ID = "00000000-0000-7000-8000-000000000000"
ME: dict[str, Any] = {"friendId": None}


async def add_friend(client: httpx.AsyncClient, name: str) -> str:
    created = await client.post(FRIENDS, json={"name": name})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def with_friends(*friend_ids: str) -> list[dict[str, Any]]:
    """The recorder plus these friends, as the equal split's participants."""
    return [ME, *({"friendId": friend_id} for friend_id in friend_ids)]


def pizza(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "total": "1000",
        "description": "Pizza",
        "occurredOn": "2026-10-23",
        "split": "equal",
    }
    return {**body, **overrides}


async def record(client: httpx.AsyncClient, **fields: Any) -> httpx.Response:
    return await client.post(SHARED, json=pizza(**fields))


async def category_id(client: httpx.AsyncClient, slug: str) -> str:
    categories = (await client.get("/api/v1/categories")).json()
    return str(next(c["id"] for c in categories if c["slug"] == slug))


def share_amounts(shared: dict[str, Any]) -> dict[str | None, int]:
    return {share["friendId"]: share["amountMinor"] for share in shared["shares"]}


def inr_total(summary: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in summary["currencies"] if c["currency"] == "INR")


async def test_a_1000_pizza_split_two_ways_counts_500_in_the_summary(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    food = await category_id(client, "food")

    response = await record(client, categoryId=food, participants=with_friends(jaymin))

    assert response.status_code == 201, response.text
    shared = response.json()
    assert shared["totalMinor"] == 100000
    assert shared["paidByYou"] is True
    assert shared["payer"]["name"] == "You"
    assert share_amounts(shared) == {None: 50000, jaymin: 50000}
    month = inr_total((await client.get(SUMMARY)).json())
    assert month["expense"]["amountMinor"] == 50000
    [food_total] = month["expenseByCategory"]
    assert (food_total["slug"], food_total["total"]["amountMinor"]) == ("food", 50000)


async def test_the_recorders_share_is_an_ordinary_expense_linked_to_the_shared_expense(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    food = await category_id(client, "food")
    shared = (await record(client, categoryId=food, participants=with_friends(jaymin))).json()

    mine = (await client.get(f"{TX}/{shared['myTransactionId']}")).json()

    assert mine["type"] == "expense"
    assert mine["amountMinor"] == 50000
    assert mine["category"]["slug"] == "food"
    assert mine["description"] == "Pizza"
    assert mine["sharedExpenseId"] == shared["id"]
    listed = (await client.get(TX)).json()["items"]
    assert [row["sharedExpenseId"] for row in listed] == [shared["id"]]


async def test_leftover_minor_units_go_to_the_payers_share(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    riya = await add_friend(client, "Riya")

    mine_paid = (await record(client, participants=with_friends(jaymin, riya))).json()
    assert share_amounts(mine_paid) == {None: 33334, jaymin: 33333, riya: 33333}

    riya_paid = (
        await record(client, payerFriendId=riya, participants=with_friends(riya), total="1000.01")
    ).json()
    assert share_amounts(riya_paid) == {None: 50000, riya: 50001}


async def test_when_a_friend_paid_only_the_user_and_that_friend_take_part(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    riya = await add_friend(client, "Riya")

    ok = await record(client, payerFriendId=jaymin, participants=with_friends(jaymin))
    assert ok.status_code == 201, ok.text
    assert ok.json()["paidByYou"] is False
    assert ok.json()["payer"]["name"] == "Jaymin"

    too_many = await record(client, payerFriendId=jaymin, participants=with_friends(jaymin, riya))
    assert too_many.status_code == 422
    assert too_many.json()["error"]["details"]["field"] == "participants"

    payer_not_in_it = await record(client, payerFriendId=jaymin, participants=with_friends(riya))
    assert payer_not_in_it.status_code == 422


async def test_exact_amounts_must_add_up_to_the_total(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")

    ok = await record(
        client,
        split="exact",
        participants=[{"friendId": None, "amount": "400"}, {"friendId": jaymin, "amount": "600"}],
    )
    assert ok.status_code == 201, ok.text
    assert share_amounts(ok.json()) == {None: 40000, jaymin: 60000}

    short = await record(
        client,
        split="exact",
        participants=[{"friendId": None, "amount": "400"}, {"friendId": jaymin, "amount": "500"}],
    )
    assert short.status_code == 422
    assert short.json()["error"]["details"]["field"] == "split"
    assert len((await client.get(SHARED)).json()) == 1  # only the good one was saved
    assert len((await client.get(TX)).json()["items"]) == 1


async def test_an_exact_split_needs_an_amount_for_everyone_and_an_equal_one_needs_none(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")

    missing = await record(client, split="exact", participants=with_friends(jaymin))
    assert missing.status_code == 422

    stray = await record(
        client,
        participants=[{"friendId": None, "amount": "400"}, {"friendId": jaymin, "amount": "600"}],
    )
    assert stray.status_code == 422


async def test_the_recorder_must_take_part_with_at_least_one_friend_and_nobody_twice(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    riya = await add_friend(client, "Riya")

    for participants in (
        [ME],
        [{"friendId": jaymin}, {"friendId": riya}],
        [ME, {"friendId": jaymin}, {"friendId": jaymin}],
    ):
        response = await record(client, participants=participants)
        assert response.status_code == 422, participants
    assert (await client.get(SHARED)).json() == []


async def test_a_friend_of_someone_else_or_an_unknown_friend_is_not_found(
    client: httpx.AsyncClient, make_client: Any
) -> None:
    await register(client)
    other = make_client()
    await register(other)
    strangers_friend = await add_friend(other, "Stranger")

    for friend_id in (strangers_friend, NO_SUCH_ID):
        response = await record(client, participants=with_friends(friend_id))
        assert response.status_code == 404, response.text


async def test_an_archived_friend_cannot_join_a_new_shared_expense(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await record(client, participants=with_friends(jaymin))
    await client.delete(f"{FRIENDS}/{jaymin}")  # has history, so archived

    response = await record(client, participants=with_friends(jaymin))

    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == "participants"


async def test_removing_a_friend_in_a_shared_expense_archives_them_and_keeps_the_name(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    loner = await add_friend(client, "Loner")
    shared = (await record(client, participants=with_friends(jaymin))).json()

    assert (await client.delete(f"{FRIENDS}/{jaymin}")).status_code == 204
    assert (await client.delete(f"{FRIENDS}/{loner}")).status_code == 204

    assert (await client.get(FRIENDS)).json() == []
    reread = (await client.get(f"{SHARED}/{shared['id']}")).json()
    assert [share["name"] for share in reread["shares"]] == ["You", "Jaymin"]


async def test_opening_a_shared_expense_shows_the_total_payer_and_every_share(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()

    opened = (await client.get(f"{SHARED}/{created['id']}")).json()

    assert opened["totalFormatted"] == created["totalFormatted"]
    assert opened["currency"] == "INR"
    assert opened["occurredOn"] == "2026-10-23"
    assert opened["payer"] == {"friendId": None, "name": "You", "isYou": True}
    assert [(s["name"], s["isYou"], s["amountMinor"]) for s in opened["shares"]] == [
        ("You", True, 50000),
        ("Jaymin", False, 50000),
    ]


async def test_shared_expenses_can_be_listed_by_date(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await record(
        client, description="Old", occurredOn="2026-09-01", participants=with_friends(jaymin)
    )
    await record(
        client, description="New", occurredOn="2026-10-20", participants=with_friends(jaymin)
    )

    everything = (await client.get(SHARED)).json()
    october = (await client.get(SHARED, params={"from": "2026-10-01"})).json()

    assert [item["description"] for item in everything] == ["New", "Old"]
    assert [item["description"] for item in october] == ["New"]


async def test_a_shared_expense_in_another_currency_stays_apart_from_rupees(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await record(client, total="30.01", currency="USD", participants=with_friends(jaymin))

    month = (await client.get(SUMMARY)).json()

    usd = next(c for c in month["currencies"] if c["currency"] == "USD")
    assert (
        usd["expense"]["amountMinor"] == 1501
    )  # 3001 split two ways; the payer takes the extra cent
    assert not [
        c for c in month["currencies"] if c["currency"] == "INR" and c["expense"]["amountMinor"]
    ]


async def test_a_future_date_or_unsupported_currency_is_refused(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    participants = with_friends(jaymin)

    future = await record(client, occurredOn="2027-01-01", participants=participants)
    assert future.status_code == 422
    assert future.json()["error"]["details"]["field"] == "occurredOn"
    odd_currency = await record(client, currency="ZZZ", participants=participants)
    assert odd_currency.status_code == 422


async def test_editing_a_shared_expense_updates_its_shares_and_the_recorders_expense_together(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    riya = await add_friend(client, "Riya")
    food = await category_id(client, "food")
    created = (await record(client, categoryId=food, participants=with_friends(jaymin))).json()

    response = await client.put(
        f"{SHARED}/{created['id']}",
        json=pizza(
            total="1500",
            description="Cab",
            occurredOn="2026-10-22",
            participants=with_friends(jaymin, riya),
        ),
    )

    assert response.status_code == 200, response.text
    edited = response.json()
    assert share_amounts(edited) == {None: 50000, jaymin: 50000, riya: 50000}
    mine = (await client.get(f"{TX}/{created['myTransactionId']}")).json()
    assert (mine["amountMinor"], mine["description"], mine["occurredOn"]) == (
        50000,
        "Cab",
        "2026-10-22",
    )
    assert mine["category"]["slug"] == "food"  # the category is the owner's, so it is kept
    month = (await client.get(SUMMARY)).json()
    assert inr_total(month)["expense"]["amountMinor"] == 50000


async def test_a_payer_can_be_changed_by_editing(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()

    edited = (
        await client.put(
            f"{SHARED}/{created['id']}",
            json=pizza(payerFriendId=jaymin, participants=with_friends(jaymin)),
        )
    ).json()

    assert edited["paidByYou"] is False
    assert edited["payer"]["name"] == "Jaymin"


async def test_a_bad_edit_changes_nothing(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()

    bad = await client.put(
        f"{SHARED}/{created['id']}",
        json=pizza(
            split="exact",
            participants=[{"friendId": None, "amount": "1"}, {"friendId": jaymin, "amount": "1"}],
        ),
    )

    assert bad.status_code == 422
    assert (await client.get(f"{SHARED}/{created['id']}")).json() == created
    assert (await client.get(f"{TX}/{created['myTransactionId']}")).json()["amountMinor"] == 50000


async def test_an_archived_friend_already_in_a_shared_expense_can_stay_through_an_edit(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()
    await client.delete(f"{FRIENDS}/{jaymin}")

    response = await client.put(
        f"{SHARED}/{created['id']}", json=pizza(total="800", participants=with_friends(jaymin))
    )

    assert response.status_code == 200, response.text
    assert share_amounts(response.json()) == {None: 40000, jaymin: 40000}


async def test_deleting_a_shared_expense_removes_the_recorders_expense_too(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()

    assert (await client.delete(f"{SHARED}/{created['id']}")).status_code == 204

    assert (await client.get(f"{SHARED}/{created['id']}")).status_code == 404
    assert (await client.get(SHARED)).json() == []
    assert (await client.get(f"{TX}/{created['myTransactionId']}")).status_code == 404
    assert (await client.get(TX)).json()["items"] == []
    month = (await client.get(SUMMARY)).json()
    assert not [c for c in month["currencies"] if c["expense"]["amountMinor"]]
    assert (await client.delete(f"{SHARED}/{created['id']}")).status_code == 404
    assert (
        await client.delete(f"{FRIENDS}/{jaymin}")
    ).status_code == 204  # history gone: no archive


async def test_another_users_shared_expense_is_not_found(
    client: httpx.AsyncClient, make_client: Any
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()
    other = make_client()
    await register(other)
    url = f"{SHARED}/{created['id']}"

    assert (await other.get(url)).status_code == 404
    assert (await other.put(url, json=pizza(participants=[ME]))).status_code == 404
    assert (await other.delete(url)).status_code == 404
    assert (await other.get(SHARED)).json() == []
    assert (await client.get(url)).status_code == 200


async def test_the_shares_amount_currency_date_and_type_are_read_only_on_the_transaction(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()
    url = f"{TX}/{created['myTransactionId']}"

    for change in (
        {"amount": "10"},
        {"currency": "USD"},
        {"occurredOn": "2026-10-01"},
        {"type": "income"},
    ):
        mine = (await client.get(url)).json()
        response = await client.patch(url, json={"version": mine["version"], **change})
        assert response.status_code == 409, (change, response.text)
        assert response.json()["error"]["code"] == "shared_expense_locked"

    assert (await client.delete(url)).status_code == 409
    assert (await client.get(url)).json()["amountMinor"] == 50000


async def test_the_shares_category_account_and_notes_stay_editable(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()
    url = f"{TX}/{created['myTransactionId']}"
    account = (await client.post("/api/v1/accounts", json={"name": "HDFC", "kind": "bank"})).json()
    mine = (await client.get(url)).json()

    response = await client.patch(
        url,
        json={
            "version": mine["version"],
            "categoryId": await category_id(client, "entertainment"),
            "accountId": account["id"],
            "notes": "Friday night",
            # Sending the unchanged amount back is fine: the form posts every field.
            "amount": "500",
        },
    )

    assert response.status_code == 200, response.text
    edited = response.json()
    assert edited["category"]["slug"] == "entertainment"
    assert edited["account"]["name"] == "HDFC"
    assert edited["notes"] == "Friday night"
    assert edited["amountMinor"] == 50000


async def test_recording_a_shared_expense_teaches_the_merchant_rule(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    food = await category_id(client, "food")

    await record(client, merchant="Dominos", categoryId=food, participants=with_friends(jaymin))

    rules = (await client.get(RULES, params={"q": "Dominos"})).json()
    assert [(rule["merchant"], rule["category"]["slug"]) for rule in rules["items"]] == [
        ("Dominos", "food")
    ]


async def test_the_shared_expense_and_the_share_are_audited_in_the_same_transaction(
    client: httpx.AsyncClient, app: Any
) -> None:
    registered = await register(client)
    jaymin = await add_friend(client, "Jaymin")
    created = (await record(client, participants=with_friends(jaymin))).json()
    await client.put(
        f"{SHARED}/{created['id']}", json=pizza(total="900", participants=with_friends(jaymin))
    )
    await client.delete(f"{SHARED}/{created['id']}")
    user_id = registered["user"]["id"]

    async with app.state.container.session_factory() as session:
        actions = list(
            (
                await session.scalars(
                    select(AuditEvent.action)
                    .where(AuditEvent.user_id == user_id)
                    .order_by(AuditEvent.created_at, AuditEvent.id)
                )
            ).all()
        )

    shared_actions = [a for a in actions if a.startswith("shared_expense.")]
    assert shared_actions == [
        "shared_expense.created",
        "shared_expense.updated",
        "shared_expense.deleted",
    ]
    assert "transaction.created" in actions
    assert "transaction.updated" in actions
    assert "transaction.deleted" in actions
