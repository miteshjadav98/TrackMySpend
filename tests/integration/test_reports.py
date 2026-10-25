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


async def test_summaries_still_work_when_redis_is_down(app: Any, client: httpx.AsyncClient) -> None:
    me = await register(client)
    await client.post(TX, json={"type": "expense", "amount": "42"})
    container = app.state.container
    dead = RedisClient.from_settings(make_settings(redis_url="redis://127.0.0.1:6390/0"))
    async with container.session_factory() as session:
        ctx = await UserService(session).context(me["user"]["id"])
        summary = await ReportService(
            session, clock=container.clock, redis=dead, generation=UserDataGeneration(dead)
        ).summary(ctx, resolve_period("this_month", ctx.today(container.clock)))
    await dead.close()
    assert summary.currencies[0].expense.amount_minor == 4200
