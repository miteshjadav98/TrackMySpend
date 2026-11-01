"""Accounts: where the user's money is held (bank, credit card, wallet, cash)."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from tests.conftest import register

ACCOUNTS = "/api/v1/accounts"


def names(response: httpx.Response) -> list[str]:
    return [account["name"] for account in response.json()]


async def test_a_new_account_uses_the_base_currency_unless_told_otherwise(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    created = await client.post(ACCOUNTS, json={"name": "  HDFC Savings ", "kind": "bank"})
    assert created.status_code == 201, created.text
    account = created.json()
    assert account["name"] == "HDFC Savings"
    assert account["kind"] == "bank"
    assert account["currency"] == "INR"
    assert account["isArchived"] is False
    assert {"id", "createdAt", "updatedAt"} <= account.keys()

    travel_card = await client.post(
        ACCOUNTS, json={"name": "Travel card", "kind": "credit_card", "currency": "usd"}
    )
    assert travel_card.json()["currency"] == "USD"

    listed = (await client.get(ACCOUNTS)).json()
    assert [a["name"] for a in listed] == ["HDFC Savings", "Travel card"]


async def test_two_active_accounts_cannot_share_a_name_ignoring_case(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    await client.post(ACCOUNTS, json={"name": "HDFC", "kind": "bank"})
    duplicate = await client.post(ACCOUNTS, json={"name": "hdfc", "kind": "credit_card"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "account_exists"
    assert len((await client.get(ACCOUNTS)).json()) == 1


async def test_a_double_submitted_new_account_is_saved_once(client: httpx.AsyncClient) -> None:
    await register(client)
    body = {"name": "Paytm", "kind": "wallet"}
    first, second = await asyncio.gather(
        client.post(ACCOUNTS, json=body), client.post(ACCOUNTS, json=body)
    )
    assert sorted([first.status_code, second.status_code]) == [201, 409]
    loser = first if first.status_code == 409 else second
    assert loser.json()["error"]["code"] == "account_exists"
    assert names(await client.get(ACCOUNTS)) == ["Paytm"]


async def test_an_account_needs_a_supported_currency_and_a_sensible_name(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    unsupported = await client.post(
        ACCOUNTS, json={"name": "Swiss", "kind": "bank", "currency": "XYZ"}
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["details"]["field"] == "currency"

    for name in ("   ", "x" * 61):
        response = await client.post(ACCOUNTS, json={"name": name, "kind": "bank"})
        assert response.status_code == 422, name
    assert (await client.post(ACCOUNTS, json={"name": "Piggy", "kind": "jar"})).status_code == 422
    assert (await client.get(ACCOUNTS)).json() == []


async def test_a_user_can_have_at_most_fifty_active_accounts(client: httpx.AsyncClient) -> None:
    await register(client)
    for number in range(1, 51):
        response = await client.post(ACCOUNTS, json={"name": f"Wallet {number}", "kind": "wallet"})
        assert response.status_code == 201, response.text
    over_the_limit = await client.post(ACCOUNTS, json={"name": "Wallet 51", "kind": "wallet"})
    assert over_the_limit.status_code == 422
    assert len((await client.get(ACCOUNTS)).json()) == 50

    # Archiving one makes room; unarchiving it while full again is over the limit.
    first = (await client.get(ACCOUNTS)).json()[0]
    await client.patch(f"{ACCOUNTS}/{first['id']}", json={"isArchived": True})
    assert (
        await client.post(ACCOUNTS, json={"name": "Wallet 51", "kind": "wallet"})
    ).status_code == 201
    unarchived = await client.patch(f"{ACCOUNTS}/{first['id']}", json={"isArchived": False})
    assert unarchived.status_code == 422
    assert len((await client.get(ACCOUNTS)).json()) == 50


async def test_an_account_can_be_renamed_and_rekinded_but_keeps_its_currency(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    account = (await client.post(ACCOUNTS, json={"name": "HDFC", "kind": "bank"})).json()
    await client.post(ACCOUNTS, json={"name": "Paytm", "kind": "wallet"})
    path = f"{ACCOUNTS}/{account['id']}"

    renamed = await client.patch(path, json={"name": "HDFC Regalia", "kind": "credit_card"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "HDFC Regalia"
    assert renamed.json()["kind"] == "credit_card"
    assert renamed.json()["currency"] == "INR"

    assert (await client.patch(path, json={"currency": "USD"})).status_code == 422
    clash = await client.patch(path, json={"name": "PAYTM"})
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "account_exists"
    unknown = f"{ACCOUNTS}/00000000-0000-7000-8000-000000000000"
    assert (await client.patch(unknown, json={"name": "Ghost"})).status_code == 404

    [stored] = [a for a in (await client.get(ACCOUNTS)).json() if a["id"] == account["id"]]
    assert (stored["name"], stored["kind"], stored["currency"]) == (
        "HDFC Regalia",
        "credit_card",
        "INR",
    )


async def test_archived_accounts_are_hidden_unless_asked_for(client: httpx.AsyncClient) -> None:
    await register(client)
    for name, kind in (("Paytm", "wallet"), ("Amazon Pay", "wallet"), ("HDFC", "bank")):
        await client.post(ACCOUNTS, json={"name": name, "kind": kind})
    amazon = next(a for a in (await client.get(ACCOUNTS)).json() if a["name"] == "Amazon Pay")
    path = f"{ACCOUNTS}/{amazon['id']}"

    archived = await client.patch(path, json={"isArchived": True})
    assert archived.status_code == 200
    assert archived.json()["isArchived"] is True

    assert names(await client.get(ACCOUNTS)) == ["HDFC", "Paytm"]
    everything = await client.get(ACCOUNTS, params={"includeArchived": "true"})
    assert names(everything) == ["HDFC", "Paytm", "Amazon Pay"]  # active first, then by name

    unarchived = await client.patch(path, json={"isArchived": False})
    assert unarchived.json()["isArchived"] is False
    assert names(await client.get(ACCOUNTS)) == ["Amazon Pay", "HDFC", "Paytm"]


async def test_an_archived_name_can_be_reused_but_not_unarchived_into_a_clash(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    old = (await client.post(ACCOUNTS, json={"name": "HDFC", "kind": "bank"})).json()
    await client.patch(f"{ACCOUNTS}/{old['id']}", json={"isArchived": True})
    reused = await client.post(ACCOUNTS, json={"name": "hdfc", "kind": "bank"})
    assert reused.status_code == 201

    clash = await client.patch(f"{ACCOUNTS}/{old['id']}", json={"isArchived": False})
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "account_exists"
    still_archived = await client.get(ACCOUNTS, params={"includeArchived": "true"})
    assert [a["isArchived"] for a in still_archived.json()] == [False, True]

    renamed_back = await client.patch(
        f"{ACCOUNTS}/{old['id']}", json={"name": "HDFC (old)", "isArchived": False}
    )
    assert renamed_back.status_code == 200
    assert names(await client.get(ACCOUNTS)) == ["hdfc", "HDFC (old)"]


async def test_every_account_change_is_audited(app: Any, client: httpx.AsyncClient) -> None:
    me = await register(client)
    account = (await client.post(ACCOUNTS, json={"name": "SBI", "kind": "bank"})).json()
    path = f"{ACCOUNTS}/{account['id']}"
    await client.patch(path, json={"name": "SBI Salary"})
    await client.patch(path, json={"name": "SBI Salary", "kind": "bank"})  # changes nothing
    await client.patch(path, json={"isArchived": True})
    await client.patch(path, json={"isArchived": False})

    async with app.state.container.session_factory() as session:
        events = (
            await session.execute(
                select(AuditEvent.action, AuditEvent.data)
                .where(
                    AuditEvent.user_id == me["user"]["id"], AuditEvent.entity_id == account["id"]
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
    assert [action for action, _ in events] == [
        "account.created",
        "account.updated",
        "account.archived",
        "account.unarchived",
    ]
    assert events[0].data == {"name": "SBI", "kind": "bank", "currency": "INR"}
    assert events[1].data == {"changes": {"name": ["SBI", "SBI Salary"]}}
