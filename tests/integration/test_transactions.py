from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from tests.conftest import register

TX = "/api/v1/transactions"


async def _category(client: httpx.AsyncClient, slug: str) -> dict[str, Any]:
    categories = (await client.get("/api/v1/categories")).json()
    return next(c for c in categories if c["slug"] == slug)


async def test_create_uses_profile_defaults_and_cleans_text(client: httpx.AsyncClient) -> None:
    await register(client)
    response = await client.post(
        TX, json={"type": "expense", "amount": "250.50", "description": "  Lunch   with  team "}
    )
    assert response.status_code == 201
    tx = response.json()
    assert tx["amountMinor"] == 25050 and tx["amount"] == "250.50" and tx["currency"] == "INR"
    assert tx["occurredOn"] == "2026-10-24"  # "today" in the user's timezone
    assert tx["description"] == "Lunch with team"
    assert tx["amountFormatted"] == "₹250.50"
    assert tx["source"] == "manual" and tx["version"] == 1


async def test_idempotency_key_prevents_duplicates(client: httpx.AsyncClient) -> None:
    await register(client)
    headers = {"Idempotency-Key": "salary-2026-10"}
    body = {"type": "income", "amount": "50000", "description": "Salary"}
    first = await client.post(TX, json=body, headers=headers)
    second = await client.post(TX, json=body, headers=headers)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    reused = await client.post(TX, json={**body, "amount": "60000"}, headers=headers)
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "idempotency_key_reused"
    assert len((await client.get(TX)).json()["items"]) == 1


async def test_validation_errors_are_specific(client: httpx.AsyncClient) -> None:
    await register(client)
    salary = await _category(client, "salary")
    cases = [
        ({"type": "expense", "amount": "10.555"}, "amount"),
        ({"type": "expense", "amount": "10", "occurredOn": "2026-10-30"}, "occurredOn"),
        ({"type": "expense", "amount": "10", "currency": "XYZ"}, "currency"),
        ({"type": "expense", "amount": "10", "categoryId": salary["id"]}, "categoryId"),
        (
            {
                "type": "expense",
                "amount": "10",
                "currency": "JPY",
                "occurredOn": "2026-10-01",
                "x": 1,
            },
            None,
        ),
        ({"type": "expense", "amount": "0"}, None),
        ({"type": "transfer", "amount": "10"}, None),
    ]
    for body, field in cases:
        response = await client.post(TX, json=body)
        assert response.status_code == 422, body
        if field:
            assert response.json()["error"]["details"]["field"] == field, body


async def test_currency_precision_follows_iso_4217(client: httpx.AsyncClient) -> None:
    await register(client)
    yen = await client.post(TX, json={"type": "expense", "amount": "500", "currency": "JPY"})
    assert yen.json()["amountMinor"] == 500
    assert (
        await client.post(TX, json={"type": "expense", "amount": "10.5", "currency": "JPY"})
    ).status_code == 422


async def test_updates_use_optimistic_concurrency(client: httpx.AsyncClient) -> None:
    await register(client)
    food = await _category(client, "food")
    tx = (
        await client.post(TX, json={"type": "expense", "amount": "200", "categoryId": food["id"]})
    ).json()
    updated = await client.patch(f"{TX}/{tx['id']}", json={"version": 1, "amount": "300"})
    assert updated.status_code == 200
    assert updated.json()["amountMinor"] == 30000 and updated.json()["version"] == 2
    stale = await client.patch(f"{TX}/{tx['id']}", json={"version": 1, "amount": "999"})
    assert stale.status_code == 409
    assert stale.json()["error"]["details"]["currentVersion"] == 2
    flipped = await client.patch(f"{TX}/{tx['id']}", json={"version": 2, "type": "income"})
    assert flipped.json()["type"] == "income" and flipped.json()["category"] is None


async def test_soft_delete_and_restore(client: httpx.AsyncClient) -> None:
    await register(client)
    tx = (await client.post(TX, json={"type": "expense", "amount": "75"})).json()
    assert (await client.delete(f"{TX}/{tx['id']}")).status_code == 204
    assert (await client.get(f"{TX}/{tx['id']}")).status_code == 404
    assert (await client.get(TX)).json()["items"] == []
    assert (await client.post(f"{TX}/{tx['id']}/restore")).status_code == 200
    assert len((await client.get(TX)).json()["items"]) == 1


async def test_keyset_pagination_is_stable(client: httpx.AsyncClient) -> None:
    await register(client)
    for day in ("2026-10-01", "2026-10-05", "2026-10-05", "2026-10-10", "2026-10-20"):
        await client.post(TX, json={"type": "expense", "amount": "10", "occurredOn": day})
    seen: list[str] = []
    dates: list[str] = []
    cursor = None
    for _ in range(5):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await client.get(TX, params=params)).json()
        seen += [item["id"] for item in page["items"]]
        dates += [item["occurredOn"] for item in page["items"]]
        cursor = page["nextCursor"]
        if not cursor:
            break
    assert len(seen) == 5 and len(set(seen)) == 5
    assert dates == sorted(dates, reverse=True)


async def test_text_search_treats_wildcards_literally(client: httpx.AsyncClient) -> None:
    await register(client)
    await client.post(
        TX, json={"type": "expense", "amount": "999", "description": "100% cotton shirt"}
    )
    await client.post(TX, json={"type": "expense", "amount": "50", "description": "Chai"})
    assert len((await client.get(TX, params={"q": "cotton"})).json()["items"]) == 1
    assert len((await client.get(TX, params={"q": "%"})).json()["items"]) == 1
    largest = (await client.get(TX, params={"sort": "largest", "limit": 1})).json()["items"]
    assert largest[0]["amountMinor"] == 99900


async def test_every_change_is_audited(app: Any, client: httpx.AsyncClient) -> None:
    me = await register(client)
    tx = (await client.post(TX, json={"type": "expense", "amount": "40"})).json()
    await client.patch(f"{TX}/{tx['id']}", json={"version": 1, "amount": "45"})
    await client.delete(f"{TX}/{tx['id']}")
    async with app.state.container.session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.user_id == me["user"]["id"], AuditEvent.entity_id == tx["id"])
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
    assert actions == ["transaction.created", "transaction.updated", "transaction.deleted"]
