"""Every financial query is scoped to the authenticated user (PRD acceptance criterion 1)."""

from __future__ import annotations

from tests.conftest import new_conversation, register, say


async def test_users_cannot_read_or_modify_each_others_data(make_client) -> None:  # type: ignore[no-untyped-def]
    alice, bob = make_client(), make_client()
    await register(alice)
    await register(bob)
    tx = (
        await alice.post("/api/v1/transactions", json={"type": "expense", "amount": "100"})
    ).json()
    path = f"/api/v1/transactions/{tx['id']}"

    assert (await bob.get(path)).status_code == 404
    assert (await bob.patch(path, json={"version": 1, "amount": "1"})).status_code == 404
    assert (await bob.delete(path)).status_code == 404
    assert (await bob.post(f"{path}/restore")).status_code == 404
    assert (await bob.get("/api/v1/transactions")).json()["items"] == []
    assert (await bob.get("/api/v1/reports/summary")).json()["transactionCount"] == 0

    conversation = await new_conversation(alice)
    assert (await bob.get(f"/api/v1/conversations/{conversation}")).status_code == 404
    await say(bob, conversation, "I spent 50 on tea", expect=404)
    assert (await bob.delete(f"/api/v1/conversations/{conversation}")).status_code == 404

    mine = (await alice.get(path)).json()
    assert mine["amountMinor"] == 10000 and mine["version"] == 1


async def test_custom_categories_are_private(make_client) -> None:  # type: ignore[no-untyped-def]
    alice, bob = make_client(), make_client()
    await register(alice)
    await register(bob)
    created = await alice.post("/api/v1/categories", json={"name": "Pet Care", "kind": "expense"})
    assert created.status_code == 201
    bob_names = {c["name"] for c in (await bob.get("/api/v1/categories")).json()}
    assert "Pet Care" not in bob_names
    response = await bob.post(
        "/api/v1/transactions",
        json={"type": "expense", "amount": "5", "categoryId": created.json()["id"]},
    )
    assert response.status_code == 404


async def test_accounts_are_private(make_client) -> None:  # type: ignore[no-untyped-def]
    alice, bob = make_client(), make_client()
    await register(alice)
    await register(bob)
    account = (await alice.post("/api/v1/accounts", json={"name": "HDFC", "kind": "bank"})).json()
    path = f"/api/v1/accounts/{account['id']}"

    assert (await bob.get("/api/v1/accounts", params={"includeArchived": "true"})).json() == []
    assert (await bob.patch(path, json={"name": "Mine now"})).status_code == 404
    assert (await bob.patch(path, json={"isArchived": True})).status_code == 404
    # Names are unique per user, so Bob's own "HDFC" does not clash with Alice's.
    assert (
        await bob.post("/api/v1/accounts", json={"name": "HDFC", "kind": "bank"})
    ).status_code == 201

    [mine] = (await alice.get("/api/v1/accounts", params={"includeArchived": "true"})).json()
    assert (mine["id"], mine["name"], mine["isArchived"]) == (account["id"], "HDFC", False)


async def test_another_users_account_cannot_tag_or_filter_my_transactions(make_client) -> None:  # type: ignore[no-untyped-def]
    alice, bob = make_client(), make_client()
    await register(alice)
    await register(bob)
    account = (await alice.post("/api/v1/accounts", json={"name": "HDFC", "kind": "bank"})).json()
    tagged = await bob.post(
        "/api/v1/transactions",
        json={"type": "expense", "amount": "5", "accountId": account["id"]},
    )
    assert tagged.status_code == 404
    assert tagged.json()["error"]["details"]["field"] == "accountId"

    tx = (await bob.post("/api/v1/transactions", json={"type": "expense", "amount": "5"})).json()
    retagged = await bob.patch(
        f"/api/v1/transactions/{tx['id']}", json={"version": 1, "accountId": account["id"]}
    )
    assert retagged.status_code == 404
    assert (await bob.get(f"/api/v1/transactions/{tx['id']}")).json()["account"] is None

    filtered = await bob.get("/api/v1/transactions", params={"accountId": account["id"]})
    assert filtered.status_code == 404
    assert filtered.json()["error"]["details"]["field"] == "accountId"
