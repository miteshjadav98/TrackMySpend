"""Transfers between two of the user's accounts, through the transactions API."""

from __future__ import annotations

from typing import Any

import httpx
from sqlalchemy import text

from tests.conftest import register

TX = "/api/v1/transactions"
ACCOUNTS = "/api/v1/accounts"
SUMMARY = "/api/v1/reports/summary"
UNKNOWN = "0190a0a0-0000-7000-8000-000000000000"


async def _account(client: httpx.AsyncClient, name: str, **fields: Any) -> dict[str, Any]:
    response = await client.post(ACCOUNTS, json={"name": name, "kind": "bank", **fields})
    assert response.status_code == 201, response.text
    return response.json()


async def _two_accounts(client: httpx.AsyncClient) -> tuple[dict[str, Any], dict[str, Any]]:
    return await _account(client, "HDFC"), await _account(client, "Paytm Wallet", kind="wallet")


async def _transfer(
    client: httpx.AsyncClient, source: dict[str, Any], target: dict[str, Any], amount: str = "10"
) -> dict[str, Any]:
    response = await client.post(
        TX,
        json={
            "type": "transfer",
            "amount": amount,
            "accountId": source["id"],
            "toAccountId": target["id"],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _field_of(response: httpx.Response) -> str:
    assert response.status_code == 422, response.text
    return str(response.json()["error"]["details"]["field"])


async def _category_id(client: httpx.AsyncClient, slug: str) -> str:
    categories = (await client.get("/api/v1/categories")).json()
    return str(next(c["id"] for c in categories if c["slug"] == slug))


# -- creating ---------------------------------------------------------------------------------


async def test_a_transfer_shows_both_accounts_and_no_category(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)

    body = await _transfer(client, hdfc, paytm, "5000")

    assert body["type"] == "transfer"
    assert body["account"] == {"id": hdfc["id"], "name": "HDFC", "kind": "bank"}
    assert body["toAccount"] == {"id": paytm["id"], "name": "Paytm Wallet", "kind": "wallet"}
    assert body["category"] is None
    read_back = (await client.get(f"{TX}/{body['id']}")).json()
    assert read_back["toAccount"]["id"] == paytm["id"]


async def test_an_expense_or_income_has_no_destination_account(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)

    expense = await client.post(
        TX, json={"type": "expense", "amount": "10", "accountId": hdfc["id"]}
    )
    assert expense.json()["toAccount"] is None

    for kind in ("expense", "income"):
        response = await client.post(
            TX,
            json={
                "type": kind,
                "amount": "10",
                "accountId": hdfc["id"],
                "toAccountId": paytm["id"],
            },
        )
        assert _field_of(response) == "toAccountId"


async def test_a_transfer_needs_both_accounts(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)

    no_from = await client.post(
        TX, json={"type": "transfer", "amount": "10", "toAccountId": paytm["id"]}
    )
    no_to = await client.post(
        TX, json={"type": "transfer", "amount": "10", "accountId": hdfc["id"]}
    )

    assert _field_of(no_from) == "accountId"
    assert _field_of(no_to) == "toAccountId"


async def test_a_transfer_cannot_go_from_an_account_to_itself(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc, _ = await _two_accounts(client)

    same = await client.post(
        TX,
        json={
            "type": "transfer",
            "amount": "10",
            "accountId": hdfc["id"],
            "toAccountId": hdfc["id"],
        },
    )

    assert _field_of(same) == "toAccountId"


async def test_a_transfer_cannot_carry_a_category(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)

    response = await client.post(
        TX,
        json={
            "type": "transfer",
            "amount": "10",
            "accountId": hdfc["id"],
            "toAccountId": paytm["id"],
            "categoryId": await _category_id(client, "food"),
        },
    )

    assert _field_of(response) == "categoryId"


async def test_a_transfer_must_be_in_the_currency_of_both_accounts(
    client: httpx.AsyncClient,
) -> None:
    await register(client)  # base currency INR
    hdfc, paytm = await _two_accounts(client)
    dollars = await _account(client, "Dollar account", currency="USD")

    wrong_amount_currency = await client.post(
        TX,
        json={
            "type": "transfer",
            "amount": "10",
            "currency": "USD",
            "accountId": hdfc["id"],
            "toAccountId": paytm["id"],
        },
    )
    mixed_accounts = await client.post(
        TX,
        json={
            "type": "transfer",
            "amount": "10",
            "accountId": hdfc["id"],
            "toAccountId": dollars["id"],
        },
    )

    assert _field_of(wrong_amount_currency) == "currency"
    assert _field_of(mixed_accounts) == "currency"


async def test_a_transfer_between_foreign_currency_accounts_takes_their_currency(
    client: httpx.AsyncClient,
) -> None:
    await register(client)  # base currency INR
    us_checking = await _account(client, "US checking", currency="USD")
    us_savings = await _account(client, "US savings", currency="USD")

    body = await _transfer(client, us_checking, us_savings, "200")

    assert body["currency"] == "USD"


async def test_an_unknown_or_archived_account_cannot_be_a_destination(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)

    unknown = await client.post(
        TX,
        json={"type": "transfer", "amount": "10", "accountId": hdfc["id"], "toAccountId": UNKNOWN},
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["details"]["field"] == "toAccountId"

    await client.patch(f"{ACCOUNTS}/{paytm['id']}", json={"isArchived": True})
    archived = await client.post(
        TX,
        json={
            "type": "transfer",
            "amount": "10",
            "accountId": hdfc["id"],
            "toAccountId": paytm["id"],
        },
    )
    assert _field_of(archived) == "toAccountId"


async def test_another_users_account_cannot_be_a_destination(make_client) -> None:  # type: ignore[no-untyped-def]
    alice, bob = make_client(), make_client()
    await register(alice)
    await register(bob)
    mine = await _account(alice, "Mine")
    theirs = await _account(bob, "Theirs")

    response = await alice.post(
        TX,
        json={
            "type": "transfer",
            "amount": "10",
            "accountId": mine["id"],
            "toAccountId": theirs["id"],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["details"]["field"] == "toAccountId"


async def test_the_database_refuses_a_malformed_transfer_row(
    app: Any, client: httpx.AsyncClient
) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)
    transfer = await _transfer(client, hdfc, paytm)
    expense = (
        await client.post(TX, json={"type": "expense", "amount": "5", "accountId": hdfc["id"]})
    ).json()

    async def update_is_accepted(sql: str, **params: str) -> bool:
        async with app.state.container.session_factory() as session:
            try:
                await session.execute(text(sql), params)
                await session.commit()
            except Exception:
                await session.rollback()
                return False
            return True

    on_transfer = "UPDATE ledger.transactions SET {} WHERE id = :id"
    same_account = on_transfer.format("to_account_id = account_id")
    no_destination = on_transfer.format("to_account_id = NULL")
    with_category = on_transfer.format("category_id = (SELECT id FROM ledger.categories LIMIT 1)")
    expense_with_destination = (
        "UPDATE ledger.transactions SET to_account_id = :to_id WHERE id = :id"
    )
    assert not await update_is_accepted(same_account, id=transfer["id"])
    assert not await update_is_accepted(no_destination, id=transfer["id"])
    assert not await update_is_accepted(with_category, id=transfer["id"])
    assert not await update_is_accepted(
        expense_with_destination, id=expense["id"], to_id=paytm["id"]
    )


# -- editing ----------------------------------------------------------------------------------


async def test_changing_an_expense_into_a_transfer_clears_its_category(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)
    expense = (
        await client.post(
            TX,
            json={
                "type": "expense",
                "amount": "300",
                "accountId": hdfc["id"],
                "categoryId": await _category_id(client, "food"),
            },
        )
    ).json()

    changed = await client.patch(
        f"{TX}/{expense['id']}",
        json={"version": 1, "type": "transfer", "toAccountId": paytm["id"]},
    )

    assert changed.status_code == 200, changed.text
    assert changed.json()["category"] is None
    assert changed.json()["account"]["id"] == hdfc["id"]
    assert changed.json()["toAccount"]["id"] == paytm["id"]


async def test_changing_an_expense_into_a_transfer_needs_both_accounts(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    hdfc, _ = await _two_accounts(client)
    untagged = (await client.post(TX, json={"type": "expense", "amount": "300"})).json()
    tagged = (
        await client.post(TX, json={"type": "expense", "amount": "300", "accountId": hdfc["id"]})
    ).json()

    no_accounts = await client.patch(
        f"{TX}/{untagged['id']}", json={"version": 1, "type": "transfer"}
    )
    no_destination = await client.patch(
        f"{TX}/{tagged['id']}", json={"version": 1, "type": "transfer"}
    )

    assert _field_of(no_accounts) == "accountId"
    assert _field_of(no_destination) == "toAccountId"
    assert (await client.get(f"{TX}/{tagged['id']}")).json()["type"] == "expense"


async def test_changing_a_transfer_into_an_expense_clears_the_destination(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)
    transfer = await _transfer(client, hdfc, paytm)

    changed = await client.patch(f"{TX}/{transfer['id']}", json={"version": 1, "type": "expense"})

    assert changed.status_code == 200, changed.text
    assert changed.json()["type"] == "expense"
    assert changed.json()["toAccount"] is None
    assert changed.json()["account"]["id"] == hdfc["id"]


async def test_a_transfer_can_be_edited_to_other_accounts_amount_and_date(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)
    cash = await _account(client, "Wallet cash", kind="cash")
    transfer = await _transfer(client, hdfc, paytm)

    changed = await client.patch(
        f"{TX}/{transfer['id']}",
        json={
            "version": 1,
            "amount": "750",
            "occurredOn": "2026-10-20",
            "toAccountId": cash["id"],
            "notes": "ATM",
        },
    )

    assert changed.status_code == 200, changed.text
    body = changed.json()
    assert (body["amountMinor"], body["occurredOn"], body["notes"]) == (75000, "2026-10-20", "ATM")
    assert body["toAccount"]["name"] == "Wallet cash"
    same = await client.patch(
        f"{TX}/{transfer['id']}", json={"version": 2, "toAccountId": hdfc["id"]}
    )
    assert _field_of(same) == "toAccountId"


async def test_editing_a_transfer_keeps_an_account_archived_since(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)
    transfer = await _transfer(client, hdfc, paytm)
    await client.patch(f"{ACCOUNTS}/{paytm['id']}", json={"isArchived": True})

    # The web dialog sends every field back, including the unchanged accounts.
    edited = await client.patch(
        f"{TX}/{transfer['id']}",
        json={
            "version": 1,
            "amount": "99",
            "accountId": hdfc["id"],
            "toAccountId": paytm["id"],
        },
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["toAccount"]["name"] == "Paytm Wallet"


# -- listing, filtering and totals ------------------------------------------------------------


async def test_the_account_filter_matches_either_end_of_a_transfer(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)
    cash = await _account(client, "Cash", kind="cash")
    await _transfer(client, hdfc, paytm, "100")
    await _transfer(client, paytm, cash, "200")
    await client.post(TX, json={"type": "expense", "amount": "300", "accountId": cash["id"]})

    def amounts(page: httpx.Response) -> list[int]:
        return sorted(tx["amountMinor"] for tx in page.json()["items"])

    assert amounts(await client.get(TX, params={"accountId": hdfc["id"]})) == [10000]
    assert amounts(await client.get(TX, params={"accountId": paytm["id"]})) == [10000, 20000]
    assert amounts(await client.get(TX, params={"accountId": cash["id"]})) == [20000, 30000]


async def test_the_type_filter_accepts_transfer(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)
    await _transfer(client, hdfc, paytm, "100")
    await client.post(TX, json={"type": "expense", "amount": "300", "accountId": hdfc["id"]})

    only_transfers = (await client.get(TX, params={"type": "transfer"})).json()["items"]

    assert [tx["type"] for tx in only_transfers] == ["transfer"]


async def test_a_transfer_changes_no_summary_total(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)
    await client.post(
        TX,
        json={
            "type": "expense",
            "amount": "350",
            "accountId": hdfc["id"],
            "categoryId": await _category_id(client, "food"),
        },
    )
    before = (await client.get(SUMMARY)).json()

    await _transfer(client, hdfc, paytm, "5000")

    after = (await client.get(SUMMARY)).json()
    assert after == before
    assert after["transactionCount"] == 1
    [inr] = after["currencies"]
    assert inr["expense"]["amountMinor"] == 35000
    assert inr["income"]["amountMinor"] == 0
    assert [c["slug"] for c in inr["expenseByCategory"]] == ["food"]


# -- merchant rules ---------------------------------------------------------------------------


async def test_a_transfer_never_teaches_a_merchant_rule(client: httpx.AsyncClient) -> None:
    await register(client)
    hdfc, paytm = await _two_accounts(client)

    created = await client.post(
        TX,
        json={
            "type": "transfer",
            "amount": "10",
            "accountId": hdfc["id"],
            "toAccountId": paytm["id"],
            "merchant": "Zomato",
        },
    )
    assert created.status_code == 201, created.text
    await client.patch(f"{TX}/{created.json()['id']}", json={"version": 1, "merchant": "Swiggy"})

    assert (await client.get("/api/v1/merchant-rules")).json()["items"] == []
