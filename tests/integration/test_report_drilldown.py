"""Chart drill-down must reconcile with the report, including Unicode names and remainders."""

from __future__ import annotations

from typing import Any

import httpx

from tests.conftest import register

TX = "/api/v1/transactions"
REPORT = "/api/v1/reports/overview"
RANGE = {"from": "2026-10-01", "to": "2026-10-03", "currency": "INR", "type": "expense"}


async def test_every_merchant_drilldown_reconciles_to_its_report_bucket_with_pagination(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    for index in range(12):
        result = await client.post(
            TX,
            json={
                "type": "expense",
                "amount": str(index + 1),
                "merchant": f"Shop {index}",
                "description": "STRASSE is mentioned here, not the merchant",
                "occurredOn": "2026-10-02",
            },
        )
        assert result.status_code == 201
    for merchant in ("Straße", "STRASSE", "Other", None):
        assert (
            await client.post(
                TX,
                json={
                    "type": "expense",
                    "amount": "100",
                    "merchant": merchant,
                    "occurredOn": "2026-10-03",
                },
            )
        ).status_code == 201
    # Neither another currency, income, a different period, nor a deleted row may affect ranking.
    for extra in (
        {"currency": "USD"},
        {"type": "income"},
        {"occurredOn": "2026-09-30"},
        {"merchant": "Deleted"},
    ):
        result = await client.post(
            TX,
            json={"type": "expense", "amount": "9999", "occurredOn": "2026-10-02", **extra},
        )
        assert result.status_code == 201
        if extra.get("merchant") == "Deleted":
            assert (await client.delete(f"{TX}/{result.json()['id']}")).status_code == 204

    report = (
        await client.get(
            REPORT, params={"period": "range", "start": RANGE["from"], "end": RANGE["to"]}
        )
    ).json()["currencies"][0]
    assert len(report["topMerchants"]) == 11
    assert any(row["key"] == "other" and not row["isOther"] for row in report["topMerchants"])
    assert any(row["key"] == "strasse" and row["count"] == 2 for row in report["topMerchants"])
    seen: set[str] = set()
    for bucket in report["topMerchants"]:
        params = {**RANGE, "limit": 1}
        params.update(
            {"otherMerchants": "true"} if bucket["isOther"] else {"merchantKey": bucket["key"]}
        )
        items: list[dict[str, Any]] = []
        while True:
            response = await client.get(TX, params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            items.extend(page["items"])
            if not page["nextCursor"]:
                break
            params["cursor"] = page["nextCursor"]
        assert len(items) == bucket["count"]
        assert sum(item["amountMinor"] for item in items) == bucket["total"]["amountMinor"]
        assert not seen.intersection(item["id"] for item in items)
        seen.update(item["id"] for item in items)
    assert len(seen) == 16


async def test_category_and_uncategorized_links_preserve_currency_and_expense_type(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    food = next(
        item for item in (await client.get("/api/v1/categories")).json() if item["slug"] == "food"
    )
    for extra in ({}, {"categoryId": food["id"]}, {"currency": "USD"}, {"type": "income"}):
        assert (
            await client.post(
                TX, json={"type": "expense", "amount": "10", "occurredOn": "2026-10-02", **extra}
            )
        ).status_code == 201
    uncategorized = (await client.get(TX, params={**RANGE, "uncategorized": "true"})).json()[
        "items"
    ]
    categorized = (await client.get(TX, params={**RANGE, "categoryId": food["id"]})).json()["items"]
    assert len(uncategorized) == len(categorized) == 1
    assert uncategorized[0]["category"] is None
    assert categorized[0]["category"]["id"] == food["id"]
    assert (
        await client.get(TX, params={"uncategorized": "true", "categoryId": food["id"]})
    ).status_code == 422


async def test_merchant_filters_are_user_scoped_and_reject_ambiguous_remainder_queries(
    make_client: Any,
) -> None:
    alice, bob = make_client(), make_client()
    await register(alice)
    await register(bob)
    await alice.post(
        TX,
        json={
            "type": "expense",
            "amount": "10",
            "merchant": "Private merchant",
            "occurredOn": "2026-10-02",
        },
    )
    for filters in ({"merchantKey": "private merchant"}, {"otherMerchants": "true"}):
        response = await bob.get(TX, params={**RANGE, **filters})
        assert response.status_code == 200
        assert response.json()["items"] == []
    for filters in (
        {"otherMerchants": "true"},
        {**RANGE, "otherMerchants": "true", "type": "income"},
        {**RANGE, "otherMerchants": "true", "from": "2000-01-01"},
        {**RANGE, "otherMerchants": "true", "merchantKey": "private merchant"},
        {"merchantKey": "   "},
    ):
        assert (await alice.get(TX, params=filters)).status_code == 422
