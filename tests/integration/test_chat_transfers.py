"""Transfers between the user's own accounts, recorded and listed through the chat."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from tests.conftest import new_conversation, register, say

ACCOUNTS = "/api/v1/accounts"
SUMMARY = "/api/v1/reports/summary"
RULES = "/api/v1/merchant-rules"
TX = "/api/v1/transactions"


@pytest.fixture
async def chat(client: httpx.AsyncClient) -> str:
    await register(client)
    return await new_conversation(client)


async def _open(client: httpx.AsyncClient, name: str, kind: str = "bank") -> dict[str, Any]:
    response = await client.post(ACCOUNTS, json={"name": name, "kind": kind})
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def _open_in(client: httpx.AsyncClient, name: str, currency: str) -> dict[str, Any]:
    response = await client.post(
        ACCOUNTS, json={"name": name, "kind": "bank", "currency": currency}
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def _accounts(client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
    return {a["name"]: a for a in (await client.get(ACCOUNTS)).json()}


def _saved(result: dict[str, Any]) -> list[dict[str, Any]]:
    card = result["assistantMessage"]["ui"][0]
    assert card["type"] == "transactions_saved", result["assistantMessage"]
    return card["transactions"]  # type: ignore[no-any-return]


def _answer(question: dict[str, Any], value: str) -> dict[str, Any]:
    return {"interactionId": question["id"], "action": "submit", "value": value}


async def test_a_transfer_between_named_accounts_saves_without_a_question(
    client: httpx.AsyncClient, chat: str
) -> None:
    hdfc, paytm = await _open(client, "HDFC"), await _open(client, "Paytm", "wallet")

    result = await say(client, chat, "moved 5000 from HDFC to Paytm")

    assert result["pendingInteraction"] is None
    [tx] = _saved(result)
    assert (tx["type"], tx["amountMinor"], tx["category"]) == ("transfer", 500000, None)
    assert (tx["account"]["id"], tx["toAccount"]["id"]) == (hdfc["id"], paytm["id"])
    assert (tx["merchant"], tx["paymentMethod"]) == (None, None)
    assert (
        result["assistantMessage"]["content"]
        == "Saved ₹5,000.00 transfer from HDFC to Paytm today."
    )


async def test_several_transfers_in_one_message_name_their_routes(
    client: httpx.AsyncClient, chat: str
) -> None:
    for name in ("HDFC", "Paytm", "SBI"):
        await _open(client, name)

    result = await say(client, chat, "moved 500 from HDFC to Paytm and moved 200 from SBI to HDFC")

    assert len(_saved(result)) == 2
    assert "HDFC → Paytm" in result["assistantMessage"]["content"]


async def test_a_missing_account_is_asked_with_the_users_accounts_as_options(
    client: httpx.AsyncClient, chat: str
) -> None:
    hdfc, paytm = await _open(client, "HDFC"), await _open(client, "Paytm", "wallet")

    first = (await say(client, chat, "moved 5000 to Paytm"))["pendingInteraction"]
    assert first["field"] == "account" and first["allowCustomInput"] is True
    assert {o["value"] for o in first["options"]} == {hdfc["id"], paytm["id"], "Cash"}

    [tx] = _saved(await say(client, chat, answer=_answer(first, hdfc["id"])))
    assert (tx["account"]["name"], tx["toAccount"]["name"]) == ("HDFC", "Paytm")


async def test_an_unknown_account_name_is_asked_about(client: httpx.AsyncClient, chat: str) -> None:
    await _open(client, "HDFC")
    await _open(client, "Paytm", "wallet")

    question = (await say(client, chat, "moved 5000 from Kotak to Paytm"))["pendingInteraction"]

    assert question["field"] == "account" and "Kotak" in question["message"]


async def test_an_ambiguous_account_name_is_asked_about(
    client: httpx.AsyncClient, chat: str
) -> None:
    savings = await _open(client, "HDFC Savings")
    await _open(client, "HDFC Salary")
    await _open(client, "Paytm", "wallet")

    question = (await say(client, chat, "moved 5000 from HDFC to Paytm"))["pendingInteraction"]
    assert question["field"] == "account"

    [tx] = _saved(await say(client, chat, answer=_answer(question, savings["id"])))
    assert tx["account"]["name"] == "HDFC Savings"


async def test_a_new_account_typed_in_a_clarification_is_created_at_save(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "HDFC")

    question = (await say(client, chat, "moved 3000 from HDFC to Paytm"))["pendingInteraction"]
    assert question["field"] == "to_account"
    assert "Paytm" not in await _accounts(client)  # nothing is created while still asking

    [tx] = _saved(await say(client, chat, "Paytm"))

    created = (await _accounts(client))["Paytm"]
    assert created["kind"] == "wallet" and created["currency"] == "INR"
    assert tx["toAccount"]["id"] == created["id"]


async def test_a_typed_credit_card_name_creates_a_credit_card(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "HDFC")
    await say(client, chat, "moved 3000 from HDFC")

    await say(client, chat, "Amex Credit Card")

    assert (await _accounts(client))["Amex Credit Card"]["kind"] == "credit_card"


async def test_choosing_the_same_account_for_both_ends_asks_again(
    client: httpx.AsyncClient, chat: str
) -> None:
    hdfc = await _open(client, "HDFC")
    await _open(client, "Paytm", "wallet")
    question = (await say(client, chat, "moved 5000 from HDFC"))["pendingInteraction"]
    assert question["field"] == "to_account"

    again = (await say(client, chat, "HDFC"))["pendingInteraction"]

    assert (
        again["field"] == "to_account"
        and "can't go to the account it came from" in again["message"]
    )
    assert hdfc["id"] not in [o["value"] for o in again["options"]]
    assert await _transactions(client) == []


async def _transactions(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    return (await client.get(TX)).json()["items"]  # type: ignore[no-any-return]


async def test_withdrawing_cash_moves_money_to_the_cash_account(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "SBI")
    cash = await _open(client, "Cash", "cash")

    [tx] = _saved(await say(client, chat, "withdrew 2000 from SBI"))

    assert (tx["type"], tx["account"]["name"], tx["toAccount"]["id"]) == (
        "transfer",
        "SBI",
        cash["id"],
    )


async def test_paying_the_credit_card_bill_moves_money_to_the_credit_card(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "HDFC")
    card = await _open(client, "ICICI Amazon Pay", "credit_card")

    [tx] = _saved(await say(client, chat, "paid 15000 credit card bill from HDFC"))

    assert (tx["account"]["name"], tx["toAccount"]["id"]) == ("HDFC", card["id"])


async def test_transfers_are_listed_and_the_summary_leaves_them_out(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "HDFC")
    await _open(client, "Paytm", "wallet")
    await say(client, chat, "moved 5000 from HDFC to Paytm")
    await say(client, chat, "spent 250 on lunch today")

    listing = await say(client, chat, "show my transfers this month")
    card = listing["assistantMessage"]["ui"][0]
    assert card["type"] == "transaction_list" and card["title"] == "Recent transfers"
    assert [t["type"] for t in card["transactions"]] == ["transfer"]

    summary = (await client.get(SUMMARY)).json()
    assert summary["transactionCount"] == 1  # the lunch only
    in_chat = await say(client, chat, "how much did I spend this month?")
    assert "₹5,000" not in in_chat["assistantMessage"]["content"]


async def test_a_transfer_in_chat_teaches_no_merchant_rule(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "HDFC")
    await _open(client, "Paytm", "wallet")

    await say(client, chat, "moved 5000 from HDFC to Paytm")

    assert (await client.get(RULES)).json()["items"] == []


async def test_a_new_account_in_a_transfer_takes_the_other_ends_currency(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open_in(client, "Wise", "USD")
    question = (await say(client, chat, "moved $100 from Wise to Revolut"))["pendingInteraction"]
    assert question["field"] == "to_account"

    [tx] = _saved(await say(client, chat, "Revolut"))

    assert (await _accounts(client))["Revolut"]["currency"] == "USD"
    assert (tx["currency"], tx["amountMinor"]) == ("USD", 10000)


async def test_a_currency_mismatch_in_a_transfer_gets_its_own_reply_and_leaves_no_account(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open_in(client, "Wise", "USD")
    await say(client, chat, "moved ₹100 from Wise to Revolut")

    result = await say(client, chat, "Revolut")

    assert "different currencies" in result["assistantMessage"]["content"]
    assert "Revolut" not in await _accounts(client)
    assert await _transactions(client) == []


async def test_the_account_limit_in_chat_gets_a_clear_reply_and_saves_nothing(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "Alpha")
    for number in range(49):
        await _open(client, f"Filler {number:02d}")
    question = (await say(client, chat, "moved 300 from Alpha to Brand New"))["pendingInteraction"]
    assert question["field"] == "to_account"

    result = await say(client, chat, "Brand New")

    assert "limit of active accounts" in result["assistantMessage"]["content"]
    assert "Brand New" not in await _accounts(client)


async def test_the_cash_option_creates_a_cash_account_when_picked(
    client: httpx.AsyncClient, chat: str
) -> None:
    await _open(client, "SBI")
    question = (await say(client, chat, "moved 2000 from SBI"))["pendingInteraction"]
    cash_option = next(o for o in question["options"] if o["label"] == "Cash")

    [tx] = _saved(await say(client, chat, answer=_answer(question, cash_option["value"])))

    created = (await _accounts(client))["Cash"]
    assert created["kind"] == "cash" and tx["toAccount"]["id"] == created["id"]
