"""Balances and settlements: who owes whom per currency, recording and deleting a settlement,
and a friend's history. Settlements never count as spending or income."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from tests.conftest import register

SETTLEMENTS = "/api/v1/settlements"
SHARED = "/api/v1/shared-expenses"
FRIENDS = "/api/v1/friends"
ACCOUNTS = "/api/v1/accounts"
TX = "/api/v1/transactions"
SUMMARY = "/api/v1/reports/summary"
NO_SUCH_ID = "00000000-0000-7000-8000-000000000000"
ME: dict[str, Any] = {"friendId": None}


async def add_friend(client: httpx.AsyncClient, name: str) -> str:
    created = await client.post(FRIENDS, json={"name": name})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def share(
    client: httpx.AsyncClient,
    friend: str,
    total: str,
    *,
    friend_paid: bool = False,
    currency: str = "INR",
    on: str = "2026-10-20",
) -> None:
    """Split `total` equally between the user and `friend`."""
    body: dict[str, Any] = {
        "total": total,
        "currency": currency,
        "description": "Dinner",
        "occurredOn": on,
        "split": "equal",
        "participants": [ME, {"friendId": friend}],
    }
    if friend_paid:
        body["payerFriendId"] = friend
    response = await client.post(SHARED, json=body)
    assert response.status_code == 201, response.text


async def settle(
    client: httpx.AsyncClient,
    friend: str,
    amount: str,
    *,
    direction: str = "friend_paid_you",
    **fields: Any,
) -> httpx.Response:
    body = {"friendId": friend, "direction": direction, "amount": amount, **fields}
    return await client.post(SETTLEMENTS, json=body)


async def balances_of(client: httpx.AsyncClient, friend: str) -> dict[str, int]:
    """Currency to the friend's balance in minor units (positive: they owe the user)."""
    friends = (await client.get(FRIENDS)).json()
    row = next(f for f in friends if f["id"] == friend)
    return {b["currency"]: b["amountMinor"] for b in row["balances"]}


async def test_a_friend_who_owes_half_a_bill_shows_a_positive_balance(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")

    assert await balances_of(client, jaymin) == {"INR": 50000}
    [row] = (await client.get(FRIENDS)).json()
    assert row["balances"][0]["formatted"].endswith("500.00")


async def test_a_friend_with_nothing_between_us_has_no_balances(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")

    assert await balances_of(client, jaymin) == {}


async def test_when_the_friend_paid_the_user_owes_them_their_share(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    riya = await add_friend(client, "Riya")
    await share(client, riya, "20", currency="USD", friend_paid=True)

    assert await balances_of(client, riya) == {"USD": -1000}


async def test_a_settlement_from_the_friend_reduces_what_they_owe(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")

    response = await settle(client, jaymin, "200", occurredOn="2026-10-22", note="UPI")

    assert response.status_code == 201, response.text
    settlement = response.json()
    assert settlement["amountMinor"] == 20000
    assert settlement["direction"] == "friend_paid_you"
    assert settlement["friend"]["name"] == "Jaymin"
    assert settlement["exceedsBalance"] is False
    assert await balances_of(client, jaymin) == {"INR": 30000}


async def test_paying_the_friend_back_reduces_what_the_user_owes(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    riya = await add_friend(client, "Riya")
    await share(client, riya, "20", currency="USD", friend_paid=True)

    await settle(client, riya, "4", direction="you_paid_friend", currency="USD")

    assert await balances_of(client, riya) == {"USD": -600}


async def test_a_balance_that_reaches_zero_is_left_out(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")

    await settle(client, jaymin, "500")

    assert await balances_of(client, jaymin) == {}


async def test_a_settlement_larger_than_the_balance_is_saved_and_the_reply_says_so(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")

    response = await settle(client, jaymin, "800")

    assert response.status_code == 201
    assert response.json()["exceedsBalance"] is True
    assert "more than" in response.json()["warning"]
    assert await balances_of(client, jaymin) == {"INR": -30000}


async def test_a_settlement_must_be_positive_dated_today_or_earlier_and_well_formed(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")

    for amount in ("0", "-5"):
        assert (await settle(client, jaymin, amount)).status_code == 422, amount
    assert (await settle(client, jaymin, "5", currency="XXX")).status_code == 422
    assert (await settle(client, jaymin, "5", direction="sideways")).status_code == 422
    assert (await settle(client, jaymin, "5", occurredOn="2999-01-01")).status_code == 422
    assert (await client.get(SETTLEMENTS)).json() == []


async def test_balances_never_mix_currencies(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    await share(client, jaymin, "20", currency="USD", friend_paid=True)

    await settle(client, jaymin, "4", currency="USD", direction="you_paid_friend")

    assert await balances_of(client, jaymin) == {"INR": 50000, "USD": -600}


async def test_a_settlement_can_be_tagged_with_an_account_of_the_users_own(
    client: httpx.AsyncClient, make_client: Any
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    bank = (await client.post(ACCOUNTS, json={"name": "HDFC", "kind": "bank"})).json()
    stranger = make_client()
    await register(stranger)
    theirs = (await stranger.post(ACCOUNTS, json={"name": "Theirs", "kind": "bank"})).json()

    tagged = await settle(client, jaymin, "100", accountId=bank["id"])
    assert tagged.status_code == 201, tagged.text
    assert tagged.json()["account"]["name"] == "HDFC"

    assert (await settle(client, jaymin, "100", accountId=theirs["id"])).status_code == 404


async def test_settlements_are_not_spending_income_or_transactions(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    before = (await client.get(SUMMARY)).json()
    transactions_before = (await client.get(TX)).json()["items"]

    await settle(client, jaymin, "500")
    await settle(client, jaymin, "50", direction="you_paid_friend")

    assert (await client.get(SUMMARY)).json() == before
    assert (await client.get(TX)).json()["items"] == transactions_before


async def test_settlements_list_newest_first_and_filter_by_friend(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    riya = await add_friend(client, "Riya")
    await settle(client, jaymin, "10", occurredOn="2026-10-01")
    await settle(client, jaymin, "20", occurredOn="2026-10-05")
    await settle(client, riya, "30", occurredOn="2026-10-03")

    everything = (await client.get(SETTLEMENTS)).json()
    assert [s["amountMinor"] for s in everything] == [2000, 3000, 1000]
    only_jaymin = (await client.get(SETTLEMENTS, params={"friendId": jaymin})).json()
    assert [s["amountMinor"] for s in only_jaymin] == [2000, 1000]


async def test_deleting_a_settlement_restores_the_balance(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    settlement = (await settle(client, jaymin, "500")).json()

    assert (await client.delete(f"{SETTLEMENTS}/{settlement['id']}")).status_code == 204

    assert await balances_of(client, jaymin) == {"INR": 50000}
    assert (await client.delete(f"{SETTLEMENTS}/{settlement['id']}")).status_code == 404


async def test_another_users_settlements_and_friends_are_404(
    client: httpx.AsyncClient, make_client: Any
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    settlement = (await settle(client, jaymin, "100")).json()
    stranger = make_client()
    await register(stranger)

    assert (await stranger.delete(f"{SETTLEMENTS}/{settlement['id']}")).status_code == 404
    assert (await settle(stranger, jaymin, "5")).status_code == 404
    assert (await stranger.get(f"{FRIENDS}/{jaymin}")).status_code == 404
    assert (await stranger.get(SETTLEMENTS)).json() == []
    assert (await client.get(f"{FRIENDS}/{NO_SUCH_ID}")).status_code == 404
    # Nothing the stranger tried touched the user's settlement (a lone 100 flips the balance).
    assert await balances_of(client, jaymin) == {"INR": -10000}


async def test_a_friend_with_a_settlement_is_archived_not_deleted(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await settle(client, jaymin, "100")
    await settle(client, jaymin, "100", direction="you_paid_friend")  # square again

    assert (await client.delete(f"{FRIENDS}/{jaymin}")).status_code == 204

    assert (await client.get(FRIENDS)).json() == []
    assert len((await client.get(SETTLEMENTS)).json()) == 2


async def test_a_friends_history_lists_shared_expenses_and_settlements_by_date(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    riya = await add_friend(client, "Riya")
    await share(client, jaymin, "1000", on="2026-10-10")
    await share(client, riya, "400", on="2026-10-12")  # not Jaymin's
    await settle(client, jaymin, "200", occurredOn="2026-10-15")
    await share(client, jaymin, "60", friend_paid=True, on="2026-10-20")

    detail = (await client.get(f"{FRIENDS}/{jaymin}")).json()

    assert detail["friend"]["name"] == "Jaymin"
    assert detail["friend"]["balances"][0]["amountMinor"] == 50000 - 20000 - 3000
    history = detail["history"]
    assert [(h["kind"], h["occurredOn"], h["effectMinor"]) for h in history] == [
        ("shared_expense", "2026-10-20", -3000),
        ("settlement", "2026-10-15", -20000),
        ("shared_expense", "2026-10-10", 50000),
    ]
    assert history[0]["label"] == "Dinner"


async def test_mixed_expenses_and_settlements_in_two_currencies_give_hand_computed_balances(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")  # INR: Jaymin owes 500.00
    await share(client, jaymin, "333.33")  # I paid; my share takes the leftover: he owes 166.66
    await share(client, jaymin, "250", friend_paid=True)  # I owe 125.00
    await share(client, jaymin, "90", currency="USD", friend_paid=True)  # USD: I owe 45.00
    await share(client, jaymin, "30", currency="USD")  # Jaymin owes 15.00
    await settle(client, jaymin, "300")  # INR: he paid me back 300.00
    await settle(client, jaymin, "100", direction="you_paid_friend")  # INR: I paid him 100.00
    await settle(client, jaymin, "10", currency="USD", direction="you_paid_friend")

    # INR: 500.00 + 166.66 - 125.00 - 300.00 + 100.00 = 341.66
    # USD: -45.00 + 15.00 + 10.00 = -20.00
    assert await balances_of(client, jaymin) == {"INR": 34166, "USD": -2000}


async def test_every_settlement_change_is_audited(app: Any, client: httpx.AsyncClient) -> None:
    me = (await register(client))["user"]["id"]
    jaymin = await add_friend(client, "Jaymin")
    settlement = (await settle(client, jaymin, "100")).json()
    await client.delete(f"{SETTLEMENTS}/{settlement['id']}")

    async with app.state.container.session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.entity_type == "settlement", AuditEvent.user_id == me)
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
    assert list(actions) == ["settlement.created", "settlement.deleted"]


async def test_a_friend_who_still_owes_money_cannot_be_removed(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")  # Jaymin owes 500

    refused = await client.delete(f"{FRIENDS}/{jaymin}")

    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "friend_has_balance"
    assert "settle up first" in refused.json()["error"]["message"].lower()
    assert await balances_of(client, jaymin) == {"INR": 50000}  # still listed, nothing archived
    await settle(client, jaymin, "500")
    assert (await client.delete(f"{FRIENDS}/{jaymin}")).status_code == 204


async def test_a_removed_friend_can_be_brought_back_with_their_history(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await share(client, jaymin, "1000")
    await settle(client, jaymin, "500")
    await client.delete(f"{FRIENDS}/{jaymin}")
    assert (await client.get(FRIENDS)).json() == []
    [archived] = (await client.get(FRIENDS, params={"archived": "true"})).json()
    assert archived["id"] == jaymin and archived["isArchived"] is True

    restored = await client.post(f"{FRIENDS}/{jaymin}/unarchive")

    assert restored.status_code == 200, restored.text
    assert restored.json()["isArchived"] is False
    assert [f["id"] for f in (await client.get(FRIENDS)).json()] == [jaymin]
    assert (await client.get(FRIENDS, params={"archived": "true"})).json() == []
    assert (await client.post(f"{FRIENDS}/{jaymin}/unarchive")).status_code == 404


async def test_another_users_archived_friend_cannot_be_brought_back(
    client: httpx.AsyncClient, make_client: Any
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    await settle(client, jaymin, "100")
    await settle(client, jaymin, "100", direction="you_paid_friend")
    await client.delete(f"{FRIENDS}/{jaymin}")
    stranger = make_client()
    await register(stranger)

    assert (await stranger.post(f"{FRIENDS}/{jaymin}/unarchive")).status_code == 404


async def test_a_retried_settlement_request_is_saved_once(client: httpx.AsyncClient) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")
    headers = {"Idempotency-Key": "settle-retry-0001"}
    body = {"friendId": jaymin, "direction": "friend_paid_you", "amount": "100"}

    first = await client.post(SETTLEMENTS, json=body, headers=headers)
    retry = await client.post(SETTLEMENTS, json=body, headers=headers)

    assert first.status_code == 201, first.text
    assert retry.status_code == 200, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert len((await client.get(SETTLEMENTS)).json()) == 1
    assert await balances_of(client, jaymin) == {"INR": -10000}
    other = await client.post(
        SETTLEMENTS, json=body, headers={"Idempotency-Key": "settle-other-02"}
    )
    assert other.status_code == 201  # a different key is a different settlement


async def test_a_settlement_without_a_key_is_never_treated_as_a_retry(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    jaymin = await add_friend(client, "Jaymin")

    await settle(client, jaymin, "100")
    await settle(client, jaymin, "100")

    assert len((await client.get(SETTLEMENTS)).json()) == 2
