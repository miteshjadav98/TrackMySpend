"""Chat workflows end to end: HTTP -> ChatService -> LangGraph -> Postgres/Redis."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from finance_api.main import create_app
from finance_core.agents.chat import ChatService
from finance_core.agents.runtime import thread_id
from finance_core.llm.base import ReplyRequest, UnderstandRequest, UnderstandResult
from finance_core.llm.resilient import ResilientLLMClient
from finance_core.llm.rules import RulesLLMClient
from finance_core.llm.schemas import ExtractedTransaction, TurnUnderstanding
from tests.conftest import new_conversation, parse_sse, register, say

TX = "/api/v1/transactions"


async def _transactions(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    return (await client.get(TX)).json()["items"]  # type: ignore[no-any-return]


def _saved(result: dict[str, Any]) -> list[dict[str, Any]]:
    card = result["assistantMessage"]["ui"][0]
    assert card["type"] == "transactions_saved", result["assistantMessage"]
    return card["transactions"]  # type: ignore[no-any-return]


class ScriptedLLM:
    """Returns a fixed understanding and/or reply, to simulate model behaviour."""

    name = "scripted"

    def __init__(self, understanding: TurnUnderstanding | None = None, reply: str = "") -> None:
        self.understanding = understanding
        self.reply = reply

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        if self.understanding is None:
            return await RulesLLMClient().understand(request)
        return UnderstandResult(understanding=self.understanding, source="scripted", latency_ms=1)

    async def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]:
        yield self.reply


class FailingLLM:
    name = "failing"

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        raise ConnectionError("provider down")

    async def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]:
        raise ConnectionError("provider down")
        yield ""  # pragma: no cover


@pytest.fixture
async def user(client: httpx.AsyncClient) -> str:
    await register(client)
    return await new_conversation(client)


# -- recording --------------------------------------------------------------------------


async def test_one_message_records_a_complete_expense(client: httpx.AsyncClient, user: str) -> None:
    result = await say(client, user, "I spent ₹350 on dinner yesterday using UPI")
    assert result["pendingInteraction"] is None
    [tx] = _saved(result)
    assert tx["amountMinor"] == 35000 and tx["currency"] == "INR"
    assert tx["category"]["slug"] == "food" and tx["occurredOn"] == "2026-10-23"
    assert tx["paymentMethod"] == "upi" and tx["description"] == "Dinner" and tx["source"] == "chat"
    assert result["assistantMessage"]["content"] == (
        "Saved ₹350.00 expense for Dinner under Food & Dining yesterday, paid by UPI."
    )
    assert len(await _transactions(client)) == 1


async def test_several_transactions_in_one_message(client: httpx.AsyncClient, user: str) -> None:
    result = await say(client, user, "uber 220 and lunch 180")
    assert [t["amountMinor"] for t in _saved(result)] == [22000, 18000]
    assert result["assistantMessage"]["content"].startswith("Saved 2 transactions")


# -- clarification ----------------------------------------------------------------------


async def test_missing_category_is_asked_then_answered_by_option(
    client: httpx.AsyncClient, user: str
) -> None:
    first = await say(client, user, "I spent 500")
    question = first["pendingInteraction"]
    assert question["type"] == "clarification" and question["field"] == "category"
    assert question["draft"]["amount"]["formatted"] == "₹500.00"
    assert "groceries" in [o["value"] for o in question["options"]]
    assert await _transactions(client) == []

    answer = await say(
        client,
        user,
        answer={"interactionId": question["id"], "action": "submit", "value": "groceries"},
    )
    [tx] = _saved(answer)
    assert tx["category"]["slug"] == "groceries" and tx["amountMinor"] == 50000

    detail = (await client.get(f"/api/v1/conversations/{user}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert detail["messages"][2]["content"] == "Groceries"  # readable transcript, not a slug
    assert detail["pendingInteraction"] is None


async def test_free_text_answers_and_custom_categories(
    client: httpx.AsyncClient, user: str
) -> None:
    await say(client, user, "paid 1200 for something")
    [tx] = _saved(await say(client, user, "electricity"))
    assert tx["category"]["slug"] == "utilities"

    await say(client, user, "spent 300 on a pottery class")
    [tx] = _saved(await say(client, user, "Hobbies"))
    assert tx["category"]["name"] == "Hobbies"
    custom = [c for c in (await client.get("/api/v1/categories")).json() if c["name"] == "Hobbies"]
    assert custom and custom[0]["isSystem"] is False


async def test_skip_and_cancel(client: httpx.AsyncClient, user: str) -> None:
    question = (await say(client, user, "I spent 75"))["pendingInteraction"]
    [tx] = _saved(
        await say(client, user, answer={"interactionId": question["id"], "action": "skip"})
    )
    assert tx["category"]["slug"] == "other"

    question = (await say(client, user, "I spent 90"))["pendingInteraction"]
    cancelled = await say(
        client, user, answer={"interactionId": question["id"], "action": "cancel"}
    )
    assert cancelled["assistantMessage"]["content"] == "Okay, I won't save that."
    assert len(await _transactions(client)) == 1


async def test_a_new_request_sets_the_unfinished_entry_aside(
    client: httpx.AsyncClient, user: str
) -> None:
    await say(client, user, "I spent 500")
    result = await say(client, user, "how much did I spend this month?")
    assert result["assistantMessage"]["ui"][0]["type"] == "summary"
    assert result["pendingInteraction"] is None
    assert await _transactions(client) == []


async def test_inferred_amounts_must_be_confirmed(
    client: httpx.AsyncClient, user: str, llm: Any
) -> None:
    llm.delegate = ScriptedLLM(
        TurnUnderstanding(
            intent="record_transactions",
            transactions=[
                ExtractedTransaction(
                    type="expense", amount="350", category="food", description="Dinner"
                )
            ],
        )
    )
    question = (await say(client, user, "three fifty for dinner"))["pendingInteraction"]
    assert question["type"] == "confirmation" and question["reason"] == "amount_unverified"
    assert await _transactions(client) == []
    [tx] = _saved(
        await say(client, user, answer={"interactionId": question["id"], "action": "submit"})
    )
    assert tx["amountMinor"] == 35000


async def test_answers_are_validated_server_side(client: httpx.AsyncClient, user: str) -> None:
    nothing_pending = await say(
        client,
        user,
        answer={"interactionId": "q-made-up", "action": "submit", "value": "x"},
        expect=422,
    )
    assert nothing_pending["error"]["code"] == "interaction_expired"
    question = (await say(client, user, "I spent 500"))["pendingInteraction"]
    wrong_id = await say(
        client,
        user,
        answer={"interactionId": "q-other", "action": "submit", "value": "food"},
        expect=422,
    )
    assert wrong_id["error"]["code"] == "interaction_expired"
    # A value the user was never offered. Custom input is allowed for categories, so use
    # the type question's closed option list instead.
    assert question["allowCustomInput"] is True
    await say(client, user, "ok skip that", expect=200)


async def test_closed_option_lists_reject_unoffered_values(
    client: httpx.AsyncClient, user: str, llm: Any
) -> None:
    llm.delegate = ScriptedLLM(
        TurnUnderstanding(
            intent="record_transactions", transactions=[ExtractedTransaction(amount="40")]
        )
    )
    question = (await say(client, user, "40 for something"))["pendingInteraction"]
    assert question["field"] == "type"
    tampered = await say(
        client,
        user,
        answer={"interactionId": question["id"], "action": "submit", "value": "transfer"},
        expect=422,
    )
    assert tampered["error"]["code"] == "invalid_interaction_response"


# -- reliability ------------------------------------------------------------------------


async def test_retried_messages_never_duplicate(client: httpx.AsyncClient, user: str) -> None:
    message_id = str(uuid.uuid4())
    first = await say(client, user, "spent 120 on coffee", client_message_id=message_id)
    again = await say(client, user, "spent 120 on coffee", client_message_id=message_id)
    assert again["replayed"] is True
    assert again["assistantMessage"]["id"] == first["assistantMessage"]["id"]
    assert len(await _transactions(client)) == 1


async def test_pending_question_survives_a_restart(
    app: Any, client: httpx.AsyncClient, user: str, settings: Any, llm: Any, clock: Any
) -> None:
    question = (await say(client, user, "I spent 500"))["pendingInteraction"]
    # A brand-new process: new pools, new compiled graph, same database.
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
        detail = (await restarted.get(f"/api/v1/conversations/{user}")).json()
        assert detail["pendingInteraction"]["id"] == question["id"]
        answer = {"interactionId": question["id"], "action": "submit", "value": "shopping"}
        [tx] = _saved(await say(restarted, user, answer=answer))
    assert tx["category"]["slug"] == "shopping"


async def test_double_texting_is_rejected_while_a_turn_runs(
    app: Any, client: httpx.AsyncClient, user: str
) -> None:
    lock = app.state.container.lock
    handle = await lock.acquire(f"conversation:{user}", ttl_seconds=30)
    try:
        busy = await say(client, user, "spent 10 on tea", expect=409)
        assert busy["error"]["code"] == "conversation_busy"
    finally:
        await lock.release(handle)
    await say(client, user, "spent 10 on tea")


async def test_gemini_outage_degrades_to_the_rules_engine(
    client: httpx.AsyncClient, user: str, llm: Any
) -> None:
    llm.delegate = ResilientLLMClient(FailingLLM(), RulesLLMClient(), timeout_seconds=2)
    [tx] = _saved(await say(client, user, "spent 250 on lunch"))
    assert tx["amountMinor"] == 25000

    llm.delegate = ResilientLLMClient(FailingLLM(), None, timeout_seconds=2)
    result = await say(client, user, "spent 99 on lunch")
    assert "trouble understanding" in result["assistantMessage"]["content"]
    assert len(await _transactions(client)) == 1


async def test_free_form_replies_cannot_state_invented_figures(
    client: httpx.AsyncClient, user: str, llm: Any
) -> None:
    llm.delegate = ScriptedLLM(
        TurnUnderstanding(intent="smalltalk"), reply="You spent ₹99,999 last month!"
    )
    result = await say(client, user, "hey")
    assert "99,999" not in result["assistantMessage"]["content"]


async def test_crash_between_graph_and_transcript_is_recovered(
    app: Any, client: httpx.AsyncClient, user: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = ChatService._save_assistant
    calls = {"n": 0}

    async def flaky(self: ChatService, *args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("process died before the reply was written")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(ChatService, "_save_assistant", flaky)
    message_id = str(uuid.uuid4())
    # What a real client sees: a 500 (the test transport would otherwise re-raise).
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
        headers={"Origin": "http://localhost:3000"},
        cookies=client.cookies,
    ) as browser:
        failed = await say(
            browser, user, "spent 640 on shoes", client_message_id=message_id, expect=500
        )
    assert failed["error"]["code"] == "internal_error"
    recovered = await say(client, user, "spent 640 on shoes", client_message_id=message_id)
    assert recovered["replayed"] is True
    assert recovered["assistantMessage"]["content"].startswith("Saved ₹640.00")
    assert len(await _transactions(client)) == 1  # the graph's save was not repeated


# -- insights, streaming, lifecycle -----------------------------------------------------


async def test_chat_summary_equals_the_reports_api(client: httpx.AsyncClient, user: str) -> None:
    await say(client, user, "I spent ₹350 on dinner yesterday using UPI")
    await say(client, user, "Got salary 50k today")
    card = (await say(client, user, "how much did I spend this month?"))["assistantMessage"]["ui"][
        0
    ]
    api = (await client.get("/api/v1/reports/summary")).json()
    assert card["summary"]["currencies"] == api["currencies"]

    biggest = (await say(client, user, "show my biggest expenses this month"))["assistantMessage"][
        "ui"
    ][0]
    assert (
        biggest["type"] == "transaction_list" and biggest["transactions"][0]["amountMinor"] == 35000
    )


async def test_streaming_turn_emits_typed_events(client: httpx.AsyncClient, user: str) -> None:
    message_id = str(uuid.uuid4())
    body = {"clientMessageId": message_id, "input": {"type": "text", "text": "spent 80 on chai"}}
    url = f"/api/v1/conversations/{user}/messages/stream"
    response = await client.post(url, json=body, headers={"Accept": "text/event-stream"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    # One cache header, and it forbids proxy compression (which would buffer the stream).
    assert response.headers.get_list("cache-control") == ["no-store, no-transform"]
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "turn.started" and names[-1] == "turn.completed"
    assert "status" in names and "text.delta" in names
    assert any(
        name == "interaction" and data["interaction"]["type"] == "transactions_saved"
        for name, data in events
    )

    replay = parse_sse((await client.post(url, json=body)).text)
    assert [name for name, _ in replay] == ["turn.completed"]
    assert replay[0][1]["result"]["replayed"] is True


async def test_input_limits(client: httpx.AsyncClient, user: str) -> None:
    await say(client, user, "", expect=422)
    await say(client, user, "x" * 4001, expect=422)


async def test_deleting_a_conversation_removes_its_checkpoints(
    app: Any, client: httpx.AsyncClient, user: str
) -> None:
    me = (await client.get("/api/v1/me")).json()
    await say(client, user, "I spent 500")
    thread = thread_id(uuid.UUID(me["user"]["id"]), uuid.UUID(user))
    count_sql = text("SELECT count(*) FROM agent.checkpoints WHERE thread_id = :t")
    async with app.state.container.engine.connect() as connection:
        assert (await connection.execute(count_sql, {"t": thread})).scalar_one() > 0
    assert (await client.delete(f"/api/v1/conversations/{user}")).status_code == 204
    async with app.state.container.engine.connect() as connection:
        assert (await connection.execute(count_sql, {"t": thread})).scalar_one() == 0
    assert (await client.get(f"/api/v1/conversations/{user}")).status_code == 404
