"""Cash positions through the public account and ledger endpoints."""

from collections.abc import Callable

import httpx

from tests.conftest import register
from tests.integration.test_friends_side import befriend, my_transactions, sign_up
from tests.integration.test_settlements import settle
from tests.integration.test_shared_expenses import add_friend, record, with_friends
from tests.integration.test_statement_imports import import_statement
from tests.integration.test_transfers import ACCOUNTS, TX, _account, _transfer


async def test_balance_signs_history_and_isolation(
    make_client: Callable[[], httpx.AsyncClient],
) -> None:
    client, other = make_client(), make_client()
    await register(client)
    await register(other)
    anchor = {"asOf": "2026-10-24", "amountMinor": 10000}
    bank = await _account(client, "Cash", balanceAnchor=anchor)
    card = await _account(client, "Card", kind="credit_card", balanceAnchor=anchor)
    unknown = await _account(client, "Loan", kind="loan", currency="USD")
    ledger = f"{ACCOUNTS}/{bank['id']}/ledger"
    assert (await other.get(ledger)).status_code == 404
    old = await client.post(
        TX,
        json={
            "type": "expense",
            "amount": "100",
            "accountId": bank["id"],
            "occurredOn": "2026-10-23",
        },
    )
    assert old.status_code == 201
    await _transfer(client, bank, card, "75")
    last = await _transfer(client, bank, card, "50")
    overview = (await client.get(ACCOUNTS + "/overview")).json()
    inr, usd = overview["positions"]
    assert [inr[k]["amountMinor"] for k in ("assets", "liabilities", "net")] == [-2500, -2500, 0]
    assert usd["excludedAccounts"][0]["id"] == unknown["id"]
    assert {a["balanceState"] for a in overview["accounts"]} == {
        "overdraft",
        "credit",
        "missing_anchor",
    }
    first = (await client.get(ledger, params={"limit": 1})).json()
    assert first["items"][0]["balanceAfter"]["amountMinor"] == -2500
    second = (await client.get(ledger, params={"offset": first["nextOffset"], "limit": 1})).json()
    assert second["items"][0]["balanceAfter"]["amountMinor"] == 2500
    assert second["nextOffset"] is None
    tx = f"{TX}/{last['id']}"
    assert (await client.delete(tx)).status_code == 204
    assert (await client.get(ledger)).json()["items"][0]["balanceAfter"]["amountMinor"] == 2500
    assert (await client.post(tx + "/restore")).status_code == 200
    assert (await client.get(ledger)).json()["items"][0]["balanceAfter"]["amountMinor"] == -2500


async def test_anchor_corrections_and_foreign_currency_effect(client: httpx.AsyncClient) -> None:
    await register(client)
    bank = await _account(client, "HDFC")
    path = f"{ACCOUNTS}/{bank['id']}"
    patch = {
        "expectedUpdatedAt": bank["updatedAt"],
        "balanceAnchor": {"asOf": "2026-10-20", "amountMinor": 0},
    }
    assert (await client.patch(path, json=patch)).json()["balanceState"] == "held"
    assert (await client.patch(path, json=patch)).status_code == 409
    assert (await client.patch(path, json={"kind": "loan"})).status_code == 409
    response = await client.post(
        TX, json={"type": "expense", "amount": "3", "currency": "USD", "accountId": bank["id"]}
    )
    assert response.status_code == 201
    [updated] = (await client.get(ACCOUNTS)).json()
    assert updated["balance"] is None and updated["balanceState"] == "currency_mismatch"
    [movement] = (await client.get(path + "/ledger")).json()["items"]
    assert movement["cashEffect"]["currency"] == "USD" and movement["balanceAfter"] is None
    clear = await client.patch(
        path, json={"expectedUpdatedAt": updated["updatedAt"], "balanceAnchor": None}
    )
    assert clear.json()["balanceState"] == "missing_anchor"


async def test_shared_payer_cash_settlement_and_import_undo(client: httpx.AsyncClient) -> None:
    await register(client)
    bank = await _account(client, "Bank", balanceAnchor={"asOf": "2026-10-01", "amountMinor": 0})
    friend = await add_friend(client, "Jay")
    fields = {"accountId": bank["id"], "participants": with_friends(friend)}
    assert (await record(client, **fields)).status_code == 201
    assert (await record(client, payerFriendId=friend, **fields)).status_code == 201
    assert (await settle(client, friend, "20", accountId=bank["id"])).status_code == 201
    ledger = f"{ACCOUNTS}/{bank['id']}/ledger"
    rows = (await client.get(ledger)).json()["items"]
    assert [(r["sourceKind"], r["cashEffect"]["amountMinor"]) for r in rows] == [
        ("settlement", 2000),
        ("shared_expense", -100000),
    ]
    imported = await import_statement(client, bank["id"])
    [after] = (await client.get(ACCOUNTS)).json()
    assert after["balance"]["amountMinor"] == -98000 + 11526038
    assert (await client.post(f"/api/v1/imports/{imported['id']}/undo")).status_code == 200
    [restored] = (await client.get(ACCOUNTS)).json()
    assert restored["balance"]["amountMinor"] == -98000


async def test_linked_payer_and_settlement_use_their_own_account(
    make_client: Callable[[], httpx.AsyncClient],
) -> None:
    recorder = await sign_up(make_client, "Recorder")
    payer = await sign_up(make_client, "Payer")
    await befriend(recorder, payer)
    bank = await _account(
        payer.http, "Bank", balanceAnchor={"asOf": "2026-10-01", "amountMinor": 0}
    )
    friend = recorder.friend[payer.name]
    shared = await record(recorder.http, payerFriendId=friend, participants=with_friends(friend))
    assert shared.status_code == 201
    [tx] = await my_transactions(payer)
    tag = await payer.http.patch(
        f"{TX}/{tx['id']}", json={"version": tx["version"], "accountId": bank["id"]}
    )
    assert tag.status_code == 200
    payment = await settle(recorder.http, friend, "500", direction="you_paid_friend")
    assert payment.status_code == 201
    path = f"/api/v1/settlements/{payment.json()['id']}"
    assert (await payer.http.patch(path, json={"accountId": bank["id"]})).status_code == 200
    [account] = (await payer.http.get(ACCOUNTS)).json()
    assert account["balance"]["amountMinor"] == -50000
    assert (await recorder.http.delete(path)).status_code == 204
    [account] = (await payer.http.get(ACCOUNTS)).json()
    assert account["balance"]["amountMinor"] == -100000
