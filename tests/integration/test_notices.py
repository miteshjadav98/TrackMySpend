"""The "Shared with you" notices: what a linked friend is told when a friend's change touches
them, and how they clear it. Two- and three-user flows over the HTTP API."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest

from tests.integration.test_friends_side import (
    FRIENDS,
    SHARED,
    MakeClient,
    Person,
    _run_tag,
    add_unlinked_friend,
    address,
    befriend,
    pizza,
    record,
    settle,
    sign_up,
)

NOTICES = "/api/v1/notices"


@pytest.fixture(autouse=True)
def _fresh_addresses() -> Iterator[None]:
    _run_tag[0] = uuid.uuid4().hex[:8]
    yield


async def notices_of(person: Person) -> dict[str, Any]:
    response = await person.http.get(NOTICES)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def messages_of(person: Person) -> list[str]:
    """The person's notices, oldest first, so a test reads in the order things happened."""
    items = reversed((await notices_of(person))["items"])
    return [item["message"] for item in items if item["id"] not in ignored]


async def linked_pair(make_client: MakeClient) -> tuple[Person, Person]:
    """Mitesh and Jaymin, linked, with the invite notices that linking leaves already read and
    forgotten, so a test sees only what it does afterwards."""
    mitesh = await sign_up(make_client, "Mitesh")
    jaymin = await sign_up(make_client, "Jaymin")
    await befriend(mitesh, jaymin)
    for person in (mitesh, jaymin):
        for item in (await notices_of(person))["items"]:
            ignored[item["id"]] = True
        await person.http.post(f"{NOTICES}/read", json={})
    return mitesh, jaymin


ignored: dict[str, bool] = {}


async def test_a_friend_is_told_when_a_shared_expense_is_added_changed_and_deleted(
    make_client: MakeClient,
) -> None:
    mitesh, jaymin = await linked_pair(make_client)

    shared = await record(mitesh, "Jaymin")
    edit = await mitesh.http.put(
        f"{SHARED}/{shared['id']}", json=pizza(mitesh, "Jaymin", total="1200")
    )
    assert edit.status_code == 200, edit.text
    assert (await mitesh.http.delete(f"{SHARED}/{shared['id']}")).status_code == 204

    added, changed, deleted = await messages_of(jaymin)
    assert added == "Mitesh added Pizza: your share is ₹500.00"
    assert changed == "Mitesh changed Pizza: your share is now ₹600.00"
    assert deleted == "Mitesh deleted Pizza"
    assert await messages_of(mitesh) == []  # the recorder is not told about their own act


async def test_marking_notices_read_clears_the_unread_count(make_client: MakeClient) -> None:
    mitesh, jaymin = await linked_pair(make_client)
    await record(mitesh, "Jaymin")
    await record(mitesh, "Jaymin", description="Tea")

    before = await notices_of(jaymin)
    assert before["unreadCount"] == 2
    assert [item["isRead"] for item in before["items"][:2]] == [False, False]

    marked = await jaymin.http.post(f"{NOTICES}/read", json={})
    assert marked.status_code == 200
    assert marked.json() == {"unreadCount": 0}
    after = await notices_of(jaymin)
    assert after["unreadCount"] == 0
    assert [item["isRead"] for item in after["items"][:2]] == [True, True]  # kept, just read


async def test_a_notice_can_be_marked_read_on_its_own(make_client: MakeClient) -> None:
    mitesh, jaymin = await linked_pair(make_client)
    await record(mitesh, "Jaymin")
    await record(mitesh, "Jaymin", description="Tea")
    newest = (await notices_of(jaymin))["items"][0]

    marked = await jaymin.http.post(f"{NOTICES}/read", json={"ids": [newest["id"]]})

    assert marked.json() == {"unreadCount": 1}


async def test_a_notice_links_to_the_friend_who_caused_it(make_client: MakeClient) -> None:
    mitesh, jaymin = await linked_pair(make_client)
    await record(mitesh, "Jaymin")

    notice = (await notices_of(jaymin))["items"][0]

    assert notice["friendId"] == jaymin.friend["Mitesh"]  # Jaymin's own row for Mitesh


async def test_nobody_else_sees_or_clears_a_users_notices(make_client: MakeClient) -> None:
    mitesh, jaymin = await linked_pair(make_client)
    riya = await sign_up(make_client, "Riya")
    await record(mitesh, "Jaymin")
    notice = (await notices_of(jaymin))["items"][0]

    assert (await notices_of(riya)) == {"unreadCount": 0, "items": []}
    await riya.http.post(f"{NOTICES}/read", json={"ids": [notice["id"]]})

    assert (await notices_of(jaymin))["unreadCount"] == 1  # Riya's attempt changed nothing


async def test_a_settlement_recorded_or_deleted_is_told_to_the_friend(
    make_client: MakeClient,
) -> None:
    mitesh, jaymin = await linked_pair(make_client)

    created = await settle(jaymin, "Mitesh", "you_paid_friend", "500")
    assert created.status_code == 201, created.text
    assert (
        await jaymin.http.delete(f"/api/v1/settlements/{created.json()['id']}")
    ).status_code == 204

    recorded, deleted = await messages_of(mitesh)
    assert recorded == "Jaymin recorded a settlement of ₹500.00"
    assert deleted == "Jaymin deleted a settlement of ₹500.00"


async def test_the_inviter_is_told_when_the_invite_is_accepted(make_client: MakeClient) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    riya = await sign_up(make_client, "Riya")

    await mitesh.http.post(FRIENDS, json={"name": "Riya D", "email": address("Riya")})
    [invite] = (await riya.http.get("/api/v1/friend-invites")).json()
    await riya.http.post(f"/api/v1/friend-invites/{invite['id']}/accept")

    assert await messages_of(mitesh) == ["Riya D accepted your friend invite"]


async def test_an_invited_user_with_an_account_is_told_about_the_pending_invite(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    riya = await sign_up(make_client, "Riya")

    await mitesh.http.post(FRIENDS, json={"name": "Riya D", "email": address("Riya")})

    assert await messages_of(riya) == ["Mitesh invited you to be friends"]


async def test_a_friend_taken_out_of_the_split_is_told_the_expense_was_removed(
    make_client: MakeClient,
) -> None:
    mitesh, jaymin = await linked_pair(make_client)
    await add_unlinked_friend(mitesh, "Sam")
    shared = await record(mitesh, "Jaymin")

    solo = await mitesh.http.put(f"{SHARED}/{shared['id']}", json=pizza(mitesh, "Sam"))
    assert solo.status_code == 200, solo.text

    assert (await messages_of(jaymin))[-1] == "Mitesh deleted Pizza"


async def test_a_friend_without_a_login_has_nobody_to_notify(make_client: MakeClient) -> None:
    mitesh = await sign_up(make_client, "Mitesh")
    await add_unlinked_friend(mitesh, "Sam")

    assert (await record(mitesh, "Sam"))["id"]
    assert await messages_of(mitesh) == []
