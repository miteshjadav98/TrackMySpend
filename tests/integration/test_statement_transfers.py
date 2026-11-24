"""Reconciling transfers across the user's statements through the import API."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from tests.conftest import register
from tests.integration.test_statement_imports import (
    IMPORTS,
    confirm,
    confirm_layout,
    transactions,
    upload,
)

SAVINGS = "hdfc_card_payment.csv"
CARD = "hdfc_rewards_card.csv"


async def create_account(
    client: httpx.AsyncClient, name: str, kind: str = "bank", currency: str = "INR"
) -> str:
    response = await client.post(
        "/api/v1/accounts", json={"name": name, "kind": kind, "currency": currency}
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def accounts(client: httpx.AsyncClient) -> tuple[str, str]:
    await register(client)
    return (
        await create_account(client, "HDFC Savings"),
        await create_account(client, "HDFC Rewards Card", "credit_card"),
    )


async def preview(client: httpx.AsyncClient, account_id: str, file: str | bytes) -> dict[str, Any]:
    detail = await upload(client, account_id, file)
    return detail if detail["layoutConfirmed"] else await confirm_layout(client, detail)


def card_side(narration: str = "PAYMENT RECEIVED. THANK YOU", day: int = 8) -> bytes:
    return f"Transaction Date,Description,Debit Amount,Credit Amount\n{day:02}/10/2026,{narration},,7500.00\n".encode()


@pytest.mark.parametrize("reverse", [False, True])
async def test_both_import_orders_record_one_transfer_and_no_spending(
    client: httpx.AsyncClient, reverse: bool
) -> None:
    bank, card = await accounts(client)
    summary_before = (await client.get("/api/v1/reports/summary")).json()
    statements = [(bank, SAVINGS, card), (card, CARD, bank)]
    if reverse:
        statements.reverse()
    for number, (account_id, fixture, other_id) in enumerate(statements):
        detail = await preview(client, account_id, fixture)
        row = detail["rows"][0]
        assert row["status"] == "transfer"
        assert row["transferAccount"]["id"] == other_id
        assert row["category"] is row["merchant"] is None
        assert row["isSelected"] is True
        assert row["matchesExistingTransfer"] is bool(number)
        assert detail["counts"]["matchedTransfers"] == number
        if number:
            assert row["note"] == "Already recorded as a transfer"
        saved = await confirm(client, detail["id"])
        assert saved["importedCount"] == 1 - number
        replay = await upload(client, account_id, fixture)
        assert replay["rows"][0]["note"] == "Already imported"

    [transfer] = await transactions(client)
    assert (transfer["type"], transfer["source"], transfer["amountMinor"]) == (
        "transfer",
        "import",
        750000,
    )
    assert (transfer["account"]["id"], transfer["toAccount"]["id"]) == (bank, card)
    assert transfer["category"] is transfer["merchant"] is transfer["paymentMethod"] is None
    summary = (await client.get("/api/v1/reports/summary")).json()
    assert summary["transactionCount"] == 0
    assert summary["currencies"] == summary_before["currencies"]


async def test_an_existing_transfer_disambiguates_a_card_payment_with_two_bank_accounts(
    client: httpx.AsyncClient,
) -> None:
    bank, card = await accounts(client)
    await create_account(client, "Axis Savings")
    unknown = await preview(client, card, CARD)
    assert unknown["rows"][0]["transferAccount"] is None

    first = await preview(client, bank, SAVINGS)
    await confirm(client, first["id"])
    conflict = await client.post(f"{IMPORTS}/{unknown['id']}/confirm")
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "transfer_matches_changed"
    credit = (await client.get(f"{IMPORTS}/{unknown['id']}")).json()
    assert credit["rows"][0]["transferAccount"]["id"] == bank
    assert credit["rows"][0]["matchesExistingTransfer"] is True
    await confirm(client, credit["id"])
    assert len(await transactions(client)) == 1


async def test_transfer_can_be_retargeted_and_rejected_without_losing_ordinary_classification(
    client: httpx.AsyncClient,
) -> None:
    bank, card = await accounts(client)
    wallet = await create_account(client, "Wallet", "wallet")
    detail = await preview(client, bank, SAVINGS)
    row = detail["rows"][0]
    assert row["transferAccount"]["id"] == card
    path = f"{IMPORTS}/{detail['id']}/rows"

    retargeted = await client.patch(
        path, json={"rows": [{"id": row["id"], "transferAccountId": wallet}]}
    )
    assert retargeted.status_code == 200
    assert retargeted.json()["rows"][0]["transferAccount"]["id"] == wallet
    rejected = await client.patch(
        path, json={"rows": [{"id": row["id"], "transferAccountId": None}]}
    )
    assert rejected.status_code == 200
    ordinary = rejected.json()["rows"][0]
    assert ordinary["status"] == "to_import"
    assert ordinary["isSelected"] is True
    assert ordinary["category"]["slug"] == "other"
    assert ordinary["transferAccount"] is None

    await confirm(client, detail["id"])
    [expense] = await transactions(client)
    assert expense["type"] == "expense"
    assert expense["toAccount"] is None


async def test_a_transfer_side_is_used_only_once_across_separate_imports(
    client: httpx.AsyncClient,
) -> None:
    bank, card = await accounts(client)
    origin = await preview(client, bank, SAVINGS)
    await confirm(client, origin["id"])
    match = await preview(client, card, CARD)
    assert (await confirm(client, match["id"]))["importedCount"] == 0

    next_payment = await preview(client, card, card_side("PAYMENT RECEIVED. SECOND PAYMENT"))
    assert next_payment["rows"][0]["matchesExistingTransfer"] is False
    assert (await confirm(client, next_payment["id"]))["importedCount"] == 1
    assert len(await transactions(client)) == 2


async def test_a_transfer_outside_the_three_day_window_is_separate(
    client: httpx.AsyncClient,
) -> None:
    bank, card = await accounts(client)
    first = await preview(client, bank, SAVINGS)
    await confirm(client, first["id"])
    second = await preview(client, card, card_side(day=9))
    assert second["rows"][0]["matchesExistingTransfer"] is False
    assert (await confirm(client, second["id"]))["importedCount"] == 1
    assert len(await transactions(client)) == 2


async def test_undoing_each_side_releases_its_rows_and_only_the_origin_removes_the_transfer(
    client: httpx.AsyncClient,
) -> None:
    bank, card = await accounts(client)
    origin = await preview(client, bank, SAVINGS)
    await confirm(client, origin["id"])
    match = await preview(client, card, CARD)
    await confirm(client, match["id"])

    assert (await client.post(f"{IMPORTS}/{match['id']}/undo")).status_code == 200
    assert len(await transactions(client)) == 1
    replay = await preview(client, card, CARD)
    assert replay["rows"][0]["matchesExistingTransfer"] is True
    assert (await confirm(client, replay["id"]))["importedCount"] == 0

    assert (await client.post(f"{IMPORTS}/{origin['id']}/undo")).status_code == 200
    assert await transactions(client) == []
    replay = await preview(client, card, CARD)
    assert replay["rows"][0]["matchesExistingTransfer"] is False
    assert (await confirm(client, replay["id"]))["importedCount"] == 1
    assert len(await transactions(client)) == 1


async def test_concurrent_confirmation_of_both_sides_cannot_create_two_transfers(
    client: httpx.AsyncClient,
) -> None:
    bank, card = await accounts(client)
    first = await preview(client, bank, SAVINGS)
    second = await preview(client, card, CARD)
    responses = await asyncio.gather(
        *(client.post(f"{IMPORTS}/{item['id']}/confirm") for item in (first, second))
    )
    assert sorted(response.status_code for response in responses) == [200, 409]
    conflict = next(response for response in responses if response.status_code == 409)
    assert conflict.json()["error"]["code"] == "transfer_matches_changed"
    import_id = conflict.request.url.path.split("/")[-2]
    detail = (await client.get(f"{IMPORTS}/{import_id}")).json()
    assert detail["rows"][0]["matchesExistingTransfer"] is True
    assert (await confirm(client, import_id))["importedCount"] == 0
    assert len(await transactions(client)) == 1


async def test_clearing_a_match_lets_the_next_selected_row_claim_it(
    client: httpx.AsyncClient,
) -> None:
    bank, card = await accounts(client)
    origin = await preview(client, bank, SAVINGS)
    await confirm(client, origin["id"])
    two_credits = card_side() + b"08/10/2026,PAYMENT RECEIVED. SECOND PAYMENT,,7500.00\n"
    detail = await preview(client, card, two_credits)
    first, second = detail["rows"]
    assert first["matchesExistingTransfer"] is True
    assert second["matchesExistingTransfer"] is False
    response = await client.patch(
        f"{IMPORTS}/{detail['id']}/rows", json={"rows": [{"id": first["id"], "isSelected": False}]}
    )
    assert response.status_code == 200
    first, second = response.json()["rows"]
    assert first["matchesExistingTransfer"] is False
    assert second["matchesExistingTransfer"] is True


async def test_transfer_target_must_be_an_active_same_currency_account_of_the_user(
    client: httpx.AsyncClient,
    make_client: Any,
) -> None:
    bank, _ = await accounts(client)
    dollar_card = await create_account(client, "USD Card", "credit_card", "USD")
    archived = await create_account(client, "Archived Card", "credit_card")
    assert (
        await client.patch(f"/api/v1/accounts/{archived}", json={"isArchived": True})
    ).status_code == 200
    intruder = make_client()
    await register(intruder)
    other_users_account = await create_account(intruder, "Foreign Owner Card", "credit_card")
    detail = await preview(client, bank, SAVINGS)
    for target, status in [
        (bank, 422),
        (dollar_card, 422),
        (archived, 422),
        (other_users_account, 404),
    ]:
        response = await client.patch(
            f"{IMPORTS}/{detail['id']}/rows",
            json={"rows": [{"id": detail["rows"][0]["id"], "transferAccountId": target}]},
        )
        assert response.status_code == status
