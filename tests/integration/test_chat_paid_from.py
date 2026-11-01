"""Expenses and income tagged with a named account through the chat. The chat never asks."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from finance_core.llm.base import ReplyRequest, UnderstandRequest, UnderstandResult
from finance_core.llm.schemas import ExtractedTransaction, TurnUnderstanding
from tests.conftest import new_conversation, register, say

ACCOUNTS = "/api/v1/accounts"
RULES = "/api/v1/merchant-rules"


class _SaysTheModelRead:
    """A model that returns one fixed reading, as the live model would for a 'from X' phrase."""

    name = "scripted"

    def __init__(self, *transactions: ExtractedTransaction) -> None:
        self._understanding = TurnUnderstanding(
            intent="record_transactions", transactions=list(transactions)
        )

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        return UnderstandResult(understanding=self._understanding, source="scripted", latency_ms=1)

    async def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]:
        yield ""


@pytest.fixture
async def chat(client: httpx.AsyncClient) -> str:
    await register(client)
    return await new_conversation(client)


async def _open(client: httpx.AsyncClient, name: str, kind: str = "bank") -> dict[str, Any]:
    response = await client.post(ACCOUNTS, json={"name": name, "kind": kind})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


def _only_saved(result: dict[str, Any]) -> dict[str, Any]:
    assert result["pendingInteraction"] is None, result["pendingInteraction"]
    card = result["assistantMessage"]["ui"][0]
    assert card["type"] == "transactions_saved", result["assistantMessage"]
    [transaction] = card["transactions"]
    return transaction  # type: ignore[no-any-return]


def _reply(result: dict[str, Any]) -> str:
    return result["assistantMessage"]["content"]  # type: ignore[no-any-return]


async def test_an_expense_paid_from_a_named_account_is_tagged_and_has_no_merchant(
    client: httpx.AsyncClient, chat: str
) -> None:
    hdfc = await _open(client, "HDFC")

    result = await say(client, chat, "paid 300 for lunch from HDFC")

    tx = _only_saved(result)
    assert tx["account"]["id"] == hdfc["id"]
    assert tx["merchant"] is None
    assert "from HDFC" in _reply(result)
    assert (await client.get(RULES)).json()[
        "items"
    ] == []  # an account never teaches a merchant rule


async def test_income_into_a_named_account_is_tagged(client: httpx.AsyncClient, chat: str) -> None:
    hdfc = await _open(client, "HDFC")

    result = await say(client, chat, "salary 50000 into HDFC")

    tx = _only_saved(result)
    assert (tx["type"], tx["account"]["id"]) == ("income", hdfc["id"])
    assert "into HDFC" in _reply(result)


async def test_an_ambiguous_account_name_saves_untagged_and_says_so(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "HDFC Savings")
    await _open(client, "HDFC Salary")

    result = await say(client, chat, "paid 300 for lunch from HDFC")

    tx = _only_saved(result)  # nothing was asked
    assert tx["account"] is None and tx["merchant"] is None
    assert "“HDFC”" in _reply(result) and "without an account" in _reply(result)


async def test_an_account_the_user_does_not_have_saves_untagged_and_says_so(
    client: httpx.AsyncClient, chat: str, llm: Any
) -> None:
    await _open(client, "HDFC")
    llm.delegate = _SaysTheModelRead(
        ExtractedTransaction(
            type="expense", amount="300", description="Lunch", account="Axis", merchant="Axis"
        )
    )

    result = await say(client, chat, "paid 300 for lunch from Axis")

    tx = _only_saved(result)
    assert tx["account"] is None and tx["merchant"] is None
    assert "“Axis”" in _reply(result)
    assert (await client.get(RULES)).json()["items"] == []
