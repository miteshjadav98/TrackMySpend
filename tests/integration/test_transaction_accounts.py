"""Tagging an expense or income with the account it was paid from or into."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from tests.conftest import register

TX = "/api/v1/transactions"
ACCOUNTS = "/api/v1/accounts"


async def _account(client: httpx.AsyncClient, name: str, **fields: Any) -> dict[str, Any]:
    response = await client.post(ACCOUNTS, json={"name": name, "kind": "bank", **fields})
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_transaction_shows_the_account_it_was_tagged_with(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    hdfc = await _account(client, "HDFC Savings")

    tagged = await client.post(
        TX, json={"type": "expense", "amount": "120", "accountId": hdfc["id"]}
    )
    untagged = await client.post(TX, json={"type": "income", "amount": "500"})

    assert tagged.status_code == 201, tagged.text
    assert tagged.json()["account"] == {"id": hdfc["id"], "name": "HDFC Savings", "kind": "bank"}
    assert untagged.json()["account"] is None
    read_back = (await client.get(f"{TX}/{tagged.json()['id']}")).json()
    assert read_back["account"]["id"] == hdfc["id"]


async def test_an_archived_account_cannot_be_picked_for_a_transaction(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    old_card = await _account(client, "Old card", kind="credit_card")
    await client.patch(f"{ACCOUNTS}/{old_card['id']}", json={"isArchived": True})

    created = await client.post(
        TX, json={"type": "expense", "amount": "60", "accountId": old_card["id"]}
    )
    assert created.status_code == 422
    assert created.json()["error"]["details"]["field"] == "accountId"

    tx = (await client.post(TX, json={"type": "expense", "amount": "60"})).json()
    retagged = await client.patch(
        f"{TX}/{tx['id']}", json={"version": 1, "accountId": old_card["id"]}
    )
    assert retagged.status_code == 422
    assert retagged.json()["error"]["details"]["field"] == "accountId"


async def test_editing_other_fields_keeps_an_account_archived_since(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    old_card = await _account(client, "Old card", kind="credit_card")
    tx = (
        await client.post(TX, json={"type": "expense", "amount": "60", "accountId": old_card["id"]})
    ).json()
    await client.patch(f"{ACCOUNTS}/{old_card['id']}", json={"isArchived": True})

    # The web dialog sends every field back, including the unchanged account.
    edited = await client.patch(
        f"{TX}/{tx['id']}",
        json={"version": 1, "amount": "75", "accountId": old_card["id"]},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["account"]["id"] == old_card["id"]
    renamed = await client.patch(f"{TX}/{tx['id']}", json={"version": 2, "notes": "Refund due"})
    assert renamed.json()["account"]["name"] == "Old card"

    cleared = await client.patch(f"{TX}/{tx['id']}", json={"version": 3, "accountId": None})
    assert cleared.status_code == 200
    assert cleared.json()["account"] is None


async def test_an_expense_may_be_paid_from_an_account_in_another_currency(
    client: httpx.AsyncClient,
) -> None:
    await register(client)  # base currency INR
    travel_card = await _account(client, "Travel card", kind="credit_card", currency="USD")
    abroad = await client.post(
        TX,
        json={
            "type": "expense",
            "amount": "1500",
            "currency": "INR",
            "accountId": travel_card["id"],
        },
    )
    assert abroad.status_code == 201, abroad.text
    assert abroad.json()["account"]["name"] == "Travel card"


async def test_the_transaction_list_filters_by_account(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc = await _account(client, "HDFC")
    paytm = await _account(client, "Paytm", kind="wallet")
    await client.post(TX, json={"type": "expense", "amount": "10", "accountId": hdfc["id"]})
    await client.post(TX, json={"type": "income", "amount": "20", "accountId": hdfc["id"]})
    await client.post(TX, json={"type": "expense", "amount": "30", "accountId": paytm["id"]})
    await client.post(TX, json={"type": "expense", "amount": "40"})

    from_hdfc = (await client.get(TX, params={"accountId": hdfc["id"]})).json()["items"]
    assert sorted(tx["amountMinor"] for tx in from_hdfc) == [1000, 2000]

    # Archived accounts stay filterable: their past transactions are still theirs.
    await client.patch(f"{ACCOUNTS}/{paytm['id']}", json={"isArchived": True})
    from_paytm = (await client.get(TX, params={"accountId": paytm["id"]})).json()["items"]
    assert [tx["amountMinor"] for tx in from_paytm] == [3000]


async def test_an_unknown_account_is_not_found(client: httpx.AsyncClient) -> None:
    await register(client)
    unknown = "0190a0a0-0000-7000-8000-000000000000"
    created = await client.post(TX, json={"type": "expense", "amount": "5", "accountId": unknown})
    assert created.status_code == 404
    assert created.json()["error"]["details"]["field"] == "accountId"
    assert (await client.get(TX)).json()["items"] == []


async def test_the_audit_trail_records_the_account(app: Any, client: httpx.AsyncClient) -> None:
    me = await register(client)
    hdfc = await _account(client, "HDFC")
    tx = (
        await client.post(TX, json={"type": "expense", "amount": "40", "accountId": hdfc["id"]})
    ).json()
    await client.patch(f"{TX}/{tx['id']}", json={"version": 1, "accountId": None})

    async with app.state.container.session_factory() as session:
        created, updated = (
            await session.scalars(
                select(AuditEvent.data)
                .where(AuditEvent.user_id == me["user"]["id"], AuditEvent.entity_id == tx["id"])
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
    assert created["accountId"] == hdfc["id"]
    assert updated["before"]["accountId"] == hdfc["id"]
    assert updated["changes"]["account_id"] == [hdfc["id"], None]
