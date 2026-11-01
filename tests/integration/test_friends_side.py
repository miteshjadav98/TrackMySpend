"""The linked friend's side of sharing: their own share, what they may see and change, and how
edits, deletes, settlements and a late invite reach them. Two- and three-user flows."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from tests.conftest import register

SHARED = "/api/v1/shared-expenses"
SETTLEMENTS = "/api/v1/settlements"
FRIENDS = "/api/v1/friends"
INVITES = "/api/v1/friend-invites"
TX = "/api/v1/transactions"
SUMMARY = "/api/v1/reports/summary"
RULES = "/api/v1/merchant-rules"
ME: dict[str, Any] = {"friendId": None}

MakeClient = Callable[[], httpx.AsyncClient]
_run_tag: list[str] = [""]


@pytest.fixture(autouse=True)
def _fresh_addresses() -> Iterator[None]:
    _run_tag[0] = uuid.uuid4().hex[:8]
    yield


def address(name: str) -> str:
    return f"{name.lower()}-{_run_tag[0]}@example.com"


class Person:
    """A signed-up user: their client, their id, and the friend rows they hold for others."""

    def __init__(self, http: httpx.AsyncClient, user_id: str, name: str) -> None:
        self.http = http
        self.id = user_id
        self.name = name
        self.friend: dict[str, str] = {}  # the other person's name to this person's friend id


async def sign_up(make_client: MakeClient, name: str) -> Person:
    http = make_client()
    registered = await register(http, displayName=name, email=address(name))
    return Person(http, registered["user"]["id"], name)


async def befriend(owner: Person, other: Person, *, as_name: str | None = None) -> None:
    """The owner adds the other by email and the other accepts, so both are linked."""
    added = await owner.http.post(
        FRIENDS, json={"name": as_name or other.name, "email": address(other.name)}
    )
    assert added.status_code == 201, added.text
    owner.friend[other.name] = added.json()["id"]
    [invite] = (await other.http.get(INVITES)).json()
    accepted = await other.http.post(f"{INVITES}/{invite['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    other.friend[owner.name] = accepted.json()["id"]


async def add_unlinked_friend(owner: Person, name: str) -> None:
    created = await owner.http.post(FRIENDS, json={"name": name})
    owner.friend[name] = created.json()["id"]


def pizza(owner: Person, *names: str, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "total": "1000",
        "description": "Pizza",
        "occurredOn": "2026-10-23",
        "split": "equal",
        "participants": [ME, *({"friendId": owner.friend[name]} for name in names)],
    }
    return {**body, **overrides}


async def record(owner: Person, *names: str, **overrides: Any) -> dict[str, Any]:
    response = await owner.http.post(SHARED, json=pizza(owner, *names, **overrides))
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def category(http: httpx.AsyncClient, slug: str) -> str:
    categories = (await http.get("/api/v1/categories")).json()
    return str(next(c["id"] for c in categories if c["slug"] == slug))


async def my_transactions(person: Person) -> list[dict[str, Any]]:
    return (await person.http.get(TX)).json()["items"]  # type: ignore[no-any-return]


async def expense_total(person: Person) -> int:
    summary = (await person.http.get(SUMMARY)).json()
    months = [c for c in summary["currencies"] if c["currency"] == "INR"]
    return int(months[0]["expense"]["amountMinor"]) if months else 0


async def balance_with(person: Person, other: str) -> int:
    friends = (await person.http.get(FRIENDS)).json()
    row = next(f for f in friends if f["id"] == person.friend[other])
    return sum(b["amountMinor"] for b in row["balances"])


async def settle(person: Person, other: str, direction: str, amount: str) -> httpx.Response:
    return await person.http.post(
        SETTLEMENTS,
        json={"friendId": person.friend[other], "direction": direction, "amount": amount},
    )


async def test_a_linked_friend_gets_their_share_as_their_own_expense_straight_away(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    await befriend(mitesh, jaymin)

    shared = await record(mitesh, "Jaymin", categoryId=await category(mitesh.http, "food"))

    [theirs] = await my_transactions(jaymin)
    assert (theirs["type"], theirs["amountMinor"], theirs["description"]) == (
        "expense",
        50000,
        "Pizza",
    )
    assert theirs["sharedExpenseId"] == shared["id"]
    assert await expense_total(jaymin) == 50000  # Jaymin's summary counts his 500
    assert await expense_total(mitesh) == 50000  # and Mitesh's own is unchanged


async def test_the_friends_category_is_their_merchant_rule_else_the_recorders_built_in_else_other(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    await befriend(mitesh, jaymin)
    food = await category(mitesh.http, "food")
    custom = (
        await mitesh.http.post("/api/v1/categories", json={"name": "Treats", "kind": "expense"})
    ).json()["id"]
    taught = await jaymin.http.post(
        TX,
        json={
            "type": "expense",
            "amount": "10",
            "merchant": "Dominos",
            "categoryId": await category(jaymin.http, "groceries"),
        },
    )
    assert taught.status_code == 201, taught.text

    await record(mitesh, "Jaymin", merchant="Dominos", categoryId=food)
    await record(mitesh, "Jaymin", merchant="Cafe", categoryId=food)
    await record(mitesh, "Jaymin", merchant="Sweets", categoryId=custom)

    shared_ones = [t for t in await my_transactions(jaymin) if t["sharedExpenseId"]]
    assert {t["merchant"]: t["category"]["slug"] for t in shared_ones} == {
        "Dominos": "groceries",
        "Cafe": "food",
        "Sweets": "other",
    }


async def test_a_friends_share_does_not_teach_their_merchant_rule_until_they_change_it(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    await befriend(mitesh, jaymin)
    await record(
        mitesh, "Jaymin", merchant="Dominos", categoryId=await category(mitesh.http, "food")
    )
    assert (await jaymin.http.get(RULES)).json()["items"] == []

    [theirs] = await my_transactions(jaymin)
    changed = await jaymin.http.patch(
        f"{TX}/{theirs['id']}",
        json={
            "version": theirs["version"],
            "categoryId": await category(jaymin.http, "entertainment"),
        },
    )

    assert changed.status_code == 200, changed.text
    [rule] = (await jaymin.http.get(RULES)).json()["items"]
    assert (rule["merchant"], rule["category"]["slug"]) == ("Dominos", "entertainment")


async def test_the_friend_edits_their_own_share_but_not_the_shared_expense(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    await befriend(mitesh, jaymin)
    shared = await record(mitesh, "Jaymin")
    [theirs] = await my_transactions(jaymin)
    url = f"{TX}/{theirs['id']}"
    account = (
        await jaymin.http.post("/api/v1/accounts", json={"name": "SBI", "kind": "bank"})
    ).json()

    tagged = await jaymin.http.patch(
        url, json={"version": theirs["version"], "accountId": account["id"], "notes": "my part"}
    )
    assert tagged.status_code == 200, tagged.text
    assert (tagged.json()["account"]["name"], tagged.json()["notes"]) == ("SBI", "my part")
    locked = await jaymin.http.patch(url, json={"version": tagged.json()["version"], "amount": "1"})
    assert locked.status_code == 409
    assert (await jaymin.http.delete(url)).status_code == 409

    edit = await jaymin.http.put(f"{SHARED}/{shared['id']}", json=pizza(mitesh, "Jaymin"))
    assert edit.status_code == 404
    assert (await jaymin.http.delete(f"{SHARED}/{shared['id']}")).status_code == 404
    assert (await mitesh.http.get(f"{SHARED}/{shared['id']}")).json()["totalMinor"] == 100000


async def test_the_friend_sees_the_bill_with_names_as_they_know_people_and_nothing_private(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    riya = await sign_up(make_client, "Riya")
    await befriend(mitesh, jaymin)
    await befriend(mitesh, riya, as_name="Ri")  # Mitesh calls her Ri
    await befriend(jaymin, riya, as_name="Riyaa")  # Jaymin calls her Riyaa
    await jaymin.http.patch(f"{FRIENDS}/{jaymin.friend['Mitesh']}", json={"name": "Mitu"})
    await add_unlinked_friend(mitesh, "Dev")  # Jaymin has no friend row for Dev
    account = (
        await mitesh.http.post("/api/v1/accounts", json={"name": "HDFC", "kind": "bank"})
    ).json()
    shared = await record(
        mitesh,
        "Jaymin",
        "Riya",
        "Dev",
        categoryId=await category(mitesh.http, "food"),
        accountId=account["id"],
    )
    mine = (await mitesh.http.get(f"{TX}/{shared['myTransactionId']}")).json()
    await mitesh.http.patch(
        f"{TX}/{mine['id']}", json={"version": mine["version"], "notes": "private note"}
    )

    seen = (await jaymin.http.get(f"{SHARED}/{shared['id']}")).json()

    assert {share["name"]: share["amountMinor"] for share in seen["shares"]} == {
        "You": 25000,
        "Mitu": 25000,
        "Riyaa": 25000,
        "Dev": 25000,
    }
    assert (seen["payer"]["name"], seen["paidByYou"], seen["totalMinor"]) == ("Mitu", False, 100000)
    text = str(seen)
    assert "HDFC" not in text and "private note" not in text
    assert not {"category", "account", "notes", "categoryId", "accountId"} & seen.keys()
    assert mitesh.friend["Riya"] not in text  # the recorder's own friend ids stay private


async def test_someone_not_in_the_expense_gets_a_404_and_the_friend_sees_no_other_transactions(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    riya = await sign_up(make_client, "Riya")
    await befriend(mitesh, jaymin)
    await befriend(mitesh, riya)
    shared = await record(mitesh, "Jaymin")
    lunch = (
        await mitesh.http.post(TX, json={"type": "expense", "amount": "80", "description": "Lunch"})
    ).json()

    assert (await riya.http.get(f"{SHARED}/{shared['id']}")).status_code == 404
    assert (await riya.http.get(SHARED)).json() == []
    assert (await jaymin.http.get(f"{SHARED}/{shared['id']}")).status_code == 200
    assert [s["id"] for s in (await jaymin.http.get(SHARED)).json()] == [shared["id"]]
    assert (await jaymin.http.get(f"{TX}/{lunch['id']}")).status_code == 404
    assert [t["description"] for t in await my_transactions(jaymin)] == ["Pizza"]
    assert await my_transactions(riya) == []


async def test_editing_and_deleting_update_every_participants_share_together(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    riya = await sign_up(make_client, "Riya")
    await befriend(mitesh, jaymin)
    await befriend(mitesh, riya)
    everyone = (mitesh, jaymin, riya)
    shared = await record(mitesh, "Jaymin", "Riya")
    assert [await expense_total(p) for p in everyone] == [33334, 33333, 33333]
    path = f"{SHARED}/{shared['id']}"

    edit = pizza(mitesh, "Jaymin", "Riya", total="900", description="Pasta")
    assert (await mitesh.http.put(path, json=edit)).status_code == 200
    assert [await expense_total(p) for p in everyone] == [30000] * 3
    assert (await my_transactions(riya))[0]["description"] == "Pasta"

    await mitesh.http.put(path, json=pizza(mitesh, "Jaymin", total="900"))
    assert [await expense_total(p) for p in everyone] == [45000, 45000, 0]
    assert (await riya.http.get(path)).status_code == 404

    await mitesh.http.put(path, json=pizza(mitesh, "Jaymin", "Riya", total="900"))
    assert await expense_total(riya) == 30000

    assert (await mitesh.http.delete(path)).status_code == 204
    assert [await my_transactions(p) for p in everyone] == [[], [], []]
    assert (await jaymin.http.get(path)).status_code == 404


async def test_balances_and_settlements_agree_on_both_sides(make_client: MakeClient) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    await befriend(mitesh, jaymin)
    await record(mitesh, "Jaymin")
    assert await balance_with(mitesh, "Jaymin") == 50000
    assert await balance_with(jaymin, "Mitesh") == -50000

    paid = await settle(jaymin, "Mitesh", "you_paid_friend", "200")
    assert paid.status_code == 201, paid.text
    assert await balance_with(mitesh, "Jaymin") == 30000
    assert await balance_with(jaymin, "Mitesh") == -30000
    [seen_by_mitesh] = (await mitesh.http.get(SETTLEMENTS)).json()
    assert seen_by_mitesh["direction"] == "friend_paid_you"
    assert seen_by_mitesh["friend"]["name"] == "Jaymin"
    # Only whoever recorded a settlement can delete it.
    assert (await mitesh.http.delete(f"{SETTLEMENTS}/{paid.json()['id']}")).status_code == 404

    assert (await settle(mitesh, "Jaymin", "friend_paid_you", "300")).status_code == 201
    assert await balance_with(mitesh, "Jaymin") == 0
    assert await balance_with(jaymin, "Mitesh") == 0
    # Both settlements were Jaymin paying Mitesh, whichever of them recorded it.
    for person, direction in ((jaymin, "you_paid_friend"), (mitesh, "friend_paid_you")):
        listed = (await person.http.get(SETTLEMENTS)).json()
        assert [s["direction"] for s in listed] == [direction, direction]
    history = (await jaymin.http.get(f"{FRIENDS}/{jaymin.friend['Mitesh']}")).json()["history"]
    assert sorted(entry["kind"] for entry in history) == [
        "settlement",
        "settlement",
        "shared_expense",
    ]


async def test_when_the_friend_paid_each_sees_the_balance_pointing_the_right_way(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    await befriend(mitesh, jaymin)

    shared = await record(mitesh, "Jaymin", payerFriendId=mitesh.friend["Jaymin"])

    assert await balance_with(mitesh, "Jaymin") == -50000
    assert await balance_with(jaymin, "Mitesh") == 50000
    seen = (await jaymin.http.get(f"{SHARED}/{shared['id']}")).json()
    assert (seen["paidByYou"], seen["payer"]["name"]) == (True, "You")


async def test_accepting_an_invite_brings_over_past_shared_expenses_and_settlements_once(
    make_client: MakeClient, app: Any
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    added = await mitesh.http.post(FRIENDS, json={"name": "Jaymin", "email": address("jaymin")})
    mitesh.friend["Jaymin"] = added.json()["id"]
    await record(mitesh, "Jaymin")
    await record(mitesh, "Jaymin", total="200", description="Tea")
    await settle(mitesh, "Jaymin", "friend_paid_you", "100")
    assert await my_transactions(jaymin) == []

    [invite] = (await jaymin.http.get(INVITES)).json()
    accepted = await jaymin.http.post(f"{INVITES}/{invite['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    jaymin.friend["Mitesh"] = accepted.json()["id"]

    assert sorted(t["description"] for t in await my_transactions(jaymin)) == ["Pizza", "Tea"]
    assert await expense_total(jaymin) == 60000
    assert await balance_with(jaymin, "Mitesh") == -(50000 + 10000 - 10000)
    assert len((await jaymin.http.get(SETTLEMENTS)).json()) == 1

    from finance_core.friends.share_delivery import ShareDelivery

    async with app.state.container.session_factory() as session:
        delivery = ShareDelivery(session, clock=app.state.container.clock)
        await delivery.bring_over_between(uuid.UUID(mitesh.id), uuid.UUID(jaymin.id))
        await session.commit()
    assert len(await my_transactions(jaymin)) == 2  # a retry creates nothing new


async def test_accepting_also_brings_over_what_the_accepter_recorded_earlier(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    # Jaymin recorded a bill with Mitesh before either was linked.
    added = await jaymin.http.post(FRIENDS, json={"name": "Mitu", "email": address("mitesh")})
    jaymin.friend["Mitesh"] = added.json()["id"]
    await record(jaymin, "Mitesh")
    [invite] = (await mitesh.http.get(INVITES)).json()
    assert (await mitesh.http.post(f"{INVITES}/{invite['id']}/accept")).status_code == 200

    assert [t["description"] for t in await my_transactions(mitesh)] == ["Pizza"]


async def test_every_affected_user_gets_an_audit_event_in_the_same_transaction(
    make_client: MakeClient, app: Any
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    await befriend(mitesh, jaymin)
    shared = await record(mitesh, "Jaymin")
    await mitesh.http.put(f"{SHARED}/{shared['id']}", json=pizza(mitesh, "Jaymin", total="900"))
    await mitesh.http.delete(f"{SHARED}/{shared['id']}")
    await settle(jaymin, "Mitesh", "you_paid_friend", "5")

    async with app.state.container.session_factory() as session:
        for person in (mitesh, jaymin):
            rows = await session.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.user_id == person.id)
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
            seen = [
                a
                for a in rows.all()
                if a.split(".")[0] in ("shared_expense", "transaction", "settlement")
            ]
            for action in (
                "shared_expense.created",
                "shared_expense.updated",
                "shared_expense.deleted",
                "transaction.created",
                "transaction.updated",
                "transaction.deleted",
                "settlement.created",
            ):
                assert seen.count(action) == 1, (person.name, action, seen)
