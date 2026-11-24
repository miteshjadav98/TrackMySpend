"""Summaries equal the ledger, per currency, and stay correct across writes (criteria 6 and 8)."""

from __future__ import annotations

from typing import Any

import httpx

from finance_core.cache import RedisClient, UserDataGeneration
from finance_core.dates import resolve_period
from finance_core.reports.service import ReportService
from finance_core.users.service import UserService
from tests.conftest import make_settings, register

TX = "/api/v1/transactions"
SUMMARY = "/api/v1/reports/summary"
OVERVIEW = "/api/v1/reports/overview"


async def _slug_ids(client: httpx.AsyncClient) -> dict[str, str]:
    return {c["slug"]: c["id"] for c in (await client.get("/api/v1/categories")).json()}


def _inr(summary: dict[str, Any]) -> dict[str, Any]:
    return next(c for c in summary["currencies"] if c["currency"] == "INR")


async def test_summary_matches_the_ledger_and_tracks_every_write(client: httpx.AsyncClient) -> None:
    await register(client)
    ids = await _slug_ids(client)
    await client.post(
        TX,
        json={
            "type": "expense",
            "amount": "350",
            "categoryId": ids["food"],
            "occurredOn": "2026-10-23",
        },
    )
    await client.post(
        TX, json={"type": "expense", "amount": "1200", "categoryId": ids["utilities"]}
    )
    await client.post(TX, json={"type": "income", "amount": "50000", "categoryId": ids["salary"]})
    await client.post(TX, json={"type": "expense", "amount": "20", "currency": "USD"})
    await client.post(
        TX, json={"type": "expense", "amount": "999", "occurredOn": "2026-09-30"}
    )  # last month

    summary = (await client.get(SUMMARY)).json()
    assert summary["period"] == {
        "start": "2026-10-01",
        "end": "2026-10-24",
        "label": "October 2026",
    }
    assert summary["transactionCount"] == 4
    assert [c["currency"] for c in summary["currencies"]] == ["INR", "USD"]  # base currency first
    inr = _inr(summary)
    assert inr["expense"]["amountMinor"] == 155000 and inr["income"]["amountMinor"] == 5000000
    assert inr["net"]["amountMinor"] == 4845000 and inr["net"]["formatted"] == "₹48,450.00"
    assert [c["slug"] for c in inr["expenseByCategory"]] == ["utilities", "food"]
    assert inr["expenseByCategory"][0]["sharePercent"] == 77.4
    assert summary["currencies"][1]["expense"]["formatted"] == "$20.00"

    # Cached reads must reflect writes immediately (generation-based invalidation).
    extra = (await client.post(TX, json={"type": "expense", "amount": "50"})).json()
    assert _inr((await client.get(SUMMARY)).json())["expense"]["amountMinor"] == 160000
    await client.patch(f"{TX}/{extra['id']}", json={"version": 1, "amount": "60"})
    assert _inr((await client.get(SUMMARY)).json())["expense"]["amountMinor"] == 161000
    await client.delete(f"{TX}/{extra['id']}")
    assert _inr((await client.get(SUMMARY)).json())["expense"]["amountMinor"] == 155000

    last_month = (await client.get(SUMMARY, params={"period": "last_month"})).json()
    assert last_month["period"]["label"] == "September 2026"
    assert _inr(last_month)["expense"]["amountMinor"] == 99900


async def test_invalid_period_is_a_validation_error(client: httpx.AsyncClient) -> None:
    await register(client)
    response = await client.get(SUMMARY, params={"period": "month", "month": "2026-13"})
    assert response.status_code == 422


async def test_overview_compares_equal_periods_and_fills_chart_gaps(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    ids = await _slug_ids(client)
    rows = [
        {
            "type": "expense",
            "amount": "10",
            "currency": "INR",
            "occurredOn": "2026-10-01",
            "categoryId": ids["food"],
            "merchant": "Swiggy",
        },
        {
            "type": "expense",
            "amount": "20",
            "currency": "INR",
            "occurredOn": "2026-10-03",
            "categoryId": ids["utilities"],
        },
        {
            "type": "income",
            "amount": "100",
            "currency": "INR",
            "occurredOn": "2026-10-04",
            "categoryId": ids["salary"],
        },
        {
            "type": "expense",
            "amount": "5",
            "currency": "USD",
            "occurredOn": "2026-10-02",
            "merchant": "Coffee Shop",
        },
        {
            "type": "expense",
            "amount": "15",
            "currency": "INR",
            "occurredOn": "2026-09-29",
            "categoryId": ids["food"],
        },
        {
            "type": "income",
            "amount": "50",
            "currency": "INR",
            "occurredOn": "2026-09-28",
            "categoryId": ids["salary"],
        },
    ]
    for row in rows:
        assert (await client.post(TX, json=row)).status_code == 201

    response = await client.get(
        OVERVIEW,
        params={"period": "range", "start": "2026-10-01", "end": "2026-10-04"},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["period"]["start"] == "2026-10-01"
    assert report["comparisonPeriod"] == {
        "start": "2026-09-27",
        "end": "2026-09-30",
        "label": "Previous 4 days",
    }
    assert report["bucketKind"] == "day"
    assert report["transactionCount"] == 4
    assert [item["currency"] for item in report["currencies"]] == ["INR", "USD"]

    inr = report["currencies"][0]
    assert inr["expense"]["current"]["amountMinor"] == 3000
    assert inr["expense"]["previous"]["amountMinor"] == 1500
    assert inr["expense"]["change"]["amountMinor"] == 1500
    assert inr["expense"]["changePercent"] == 100.0
    assert inr["income"]["current"]["amountMinor"] == 10000
    assert inr["net"]["current"]["amountMinor"] == 7000
    assert [item["total"]["amountMinor"] for item in inr["expenseByCategory"]] == [
        2000,
        1000,
    ]
    assert [(item["name"], item["total"]["amountMinor"]) for item in inr["topMerchants"]] == [
        ("Swiggy", 1000),
        ("Other merchants", 2000),
    ]
    assert [point["expense"]["amountMinor"] for point in inr["trend"]] == [1000, 0, 2000, 0]
    assert [point["income"]["amountMinor"] for point in inr["trend"]] == [0, 0, 0, 10000]

    usd = report["currencies"][1]
    assert usd["expense"]["current"]["amountMinor"] == 500
    assert usd["expense"]["previous"]["amountMinor"] == 0
    assert usd["expense"]["changePercent"] is None

    # The generation-keyed cache cannot hide a later ledger write.
    await client.post(
        TX,
        json={
            "type": "expense",
            "amount": "1",
            "occurredOn": "2026-10-02",
            "categoryId": ids["food"],
        },
    )
    refreshed = (
        await client.get(
            OVERVIEW,
            params={"period": "range", "start": "2026-10-01", "end": "2026-10-04"},
        )
    ).json()
    assert refreshed["currencies"][0]["expense"]["current"]["amountMinor"] == 3100


async def test_overview_counts_the_users_share_but_not_transfers_or_deleted_rows(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    friend = (await client.post("/api/v1/friends", json={"name": "Jaymin"})).json()
    shared = await client.post(
        "/api/v1/shared-expenses",
        json={
            "total": "1000",
            "occurredOn": "2026-10-23",
            "description": "Pizza",
            "split": "equal",
            "participants": [{"friendId": None}, {"friendId": friend["id"]}],
        },
    )
    assert shared.status_code == 201, shared.text

    first = (await client.post("/api/v1/accounts", json={"name": "HDFC", "kind": "bank"})).json()
    second = (await client.post("/api/v1/accounts", json={"name": "Cash", "kind": "cash"})).json()
    transfer = await client.post(
        TX,
        json={
            "type": "transfer",
            "amount": "100",
            "occurredOn": "2026-10-23",
            "accountId": first["id"],
            "toAccountId": second["id"],
        },
    )
    assert transfer.status_code == 201, transfer.text
    deleted = (
        await client.post(TX, json={"type": "expense", "amount": "99", "occurredOn": "2026-10-23"})
    ).json()
    assert (await client.delete(f"{TX}/{deleted['id']}")).status_code == 204

    report = (await client.get(OVERVIEW)).json()

    assert report["transactionCount"] == 1
    assert report["currencies"][0]["expense"]["current"]["amountMinor"] == 50000


async def test_summaries_still_work_when_redis_is_down(app: Any, client: httpx.AsyncClient) -> None:
    me = await register(client)
    await client.post(TX, json={"type": "expense", "amount": "42"})
    container = app.state.container
    dead = RedisClient.from_settings(make_settings(redis_url="redis://127.0.0.1:6390/0"))
    async with container.session_factory() as session:
        ctx = await UserService(session).context(me["user"]["id"])
        service = ReportService(
            session, clock=container.clock, redis=dead, generation=UserDataGeneration(dead)
        )
        period = resolve_period("this_month", ctx.today(container.clock))
        summary = await service.summary(ctx, period)
        overview = await service.overview(ctx, period)
    await dead.close()
    assert summary.currencies[0].expense.amount_minor == 4200
    assert overview.currencies[0].expense.current.amount_minor == 4200
