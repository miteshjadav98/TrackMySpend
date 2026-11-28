"""Chat reports use the overview's exact values and survive replay and process restarts."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from finance_api.main import create_app
from finance_core.llm.schemas import ExtractedTransaction, TurnUnderstanding
from tests.conftest import new_conversation, register, say
from tests.integration.test_chat import ScriptedLLM


def report_card(result: dict[str, Any]) -> dict[str, Any]:
    return next(item for item in result["assistantMessage"]["ui"] if item["type"] == "report")


@pytest.mark.parametrize(
    "kind,phrase",
    [
        ("trend", "show my spending trend"),
        ("breakdown", "show my spending breakdown"),
        ("insights", "show spending insights"),
    ],
)
async def test_chat_report_matches_the_overview_and_never_records_period_numbers(
    client: httpx.AsyncClient,
    kind: str,
    phrase: str,
) -> None:
    await register(client)
    for currency in ("INR", "USD"):
        assert (
            await client.post(
                "/api/v1/transactions",
                json={
                    "type": "expense",
                    "amount": "10.01",
                    "currency": currency,
                    "merchant": "Coffee Shop",
                    "occurredOn": "2026-10-02",
                },
            )
        ).status_code == 201
    conversation = await new_conversation(client)
    card = report_card(await say(client, conversation, f"{phrase} for the past 3 months"))
    assert card["kind"] == kind and card["version"] == 1
    assert card["availableCurrencies"] == ["INR", "USD"]
    params = parse_qs(urlsplit(card["reportHref"]).query)
    assert params == {
        "period": ["range"],
        "start": ["2026-08-01"],
        "end": ["2026-10-24"],
        "currency": ["INR"],
    }
    overview = (
        await client.get(
            "/api/v1/reports/overview",
            params={
                "period": "range",
                "start": card["period"]["start"],
                "end": card["period"]["end"],
            },
        )
    ).json()
    selected = overview["currencies"][0]
    assert card["period"] == overview["period"]
    assert card["comparisonPeriod"] == overview["comparisonPeriod"]
    assert card["preview"]["expense"] == selected["expense"]
    dimension = {"trend": "trend", "breakdown": "expenseByCategory", "insights": "insights"}[kind]
    assert card["preview"][dimension] == selected[dimension]
    assert len((await client.get("/api/v1/transactions")).json()["items"]) == 2
    summary = await say(client, conversation, "how much did I spend this month?")
    assert summary["assistantMessage"]["ui"][0]["type"] == "summary"
    assert all(item["type"] != "report" for item in summary["assistantMessage"]["ui"])


async def test_report_snapshot_survives_retry_reload_and_new_process(
    client: httpx.AsyncClient,
    settings: Any,
    llm: Any,
    clock: Any,
) -> None:
    await register(client)
    await client.post(
        "/api/v1/transactions", json={"type": "expense", "amount": "9", "currency": "USD"}
    )
    conversation = await new_conversation(client)
    message_id = str(uuid.uuid4())
    text = "show USD spending trend this month"
    card = report_card(await say(client, conversation, text, client_message_id=message_id))
    assert card["currency"] == "USD" and card["preview"]["expense"]["current"]["amountMinor"] == 900
    await client.post(
        "/api/v1/transactions", json={"type": "expense", "amount": "20", "currency": "USD"}
    )
    assert report_card(await say(client, conversation, text, client_message_id=message_id)) == card
    second = create_app(settings, llm=llm, clock=clock)
    async with (
        second.router.lifespan_context(second),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=second),
            base_url="http://testserver",
            headers={"Origin": "http://localhost:3000"},
            cookies=client.cookies,
        ) as restarted,
    ):
        detail = (await restarted.get(f"/api/v1/conversations/{conversation}")).json()
        stored = next(message for message in detail["messages"] if message["role"] == "assistant")
        assert next(item for item in stored["ui"] if item["type"] == "report") == card
        fresh = report_card(await say(restarted, conversation, text))
        assert fresh["preview"]["expense"]["current"]["amountMinor"] == 2900


async def test_report_abandons_old_clarification_and_ignores_provider_amounts(
    client: httpx.AsyncClient,
    llm: Any,
) -> None:
    await register(client)
    conversation = await new_conversation(client)
    assert (await say(client, conversation, "spent 500"))["pendingInteraction"]
    llm.delegate = ScriptedLLM(
        TurnUnderstanding(
            intent="record_transactions",
            transactions=[
                ExtractedTransaction(type="expense", amount="6", category="food"),
            ],
        )
    )
    result = await say(client, conversation, "show my spending trend for six months")
    assert result["pendingInteraction"] is None
    assert report_card(result)["preview"] is None
    assert (await client.get("/api/v1/transactions")).json()["items"] == []


async def test_invalid_report_range_is_not_silently_replaced(client: httpx.AsyncClient) -> None:
    await register(client)
    result = await say(
        client, await new_conversation(client), "show spending trend from 2026-10-24 to 2026-10-01"
    )
    assert "invalid" in result["assistantMessage"]["content"]
    assert all(item["type"] != "report" for item in result["assistantMessage"]["ui"])
