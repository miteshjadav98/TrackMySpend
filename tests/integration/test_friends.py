"""Friends list and invites: adding, renaming, removing, and linking two users by invite."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from tests.conftest import register

FRIENDS = "/api/v1/friends"
INVITES = "/api/v1/friend-invites"
NO_SUCH_ID = "00000000-0000-7000-8000-000000000000"

MakeClient = Callable[[], httpx.AsyncClient]

_run_tag: list[str] = [""]


@pytest.fixture(autouse=True)
def _fresh_addresses() -> Iterator[None]:
    """Every test gets its own email addresses, so one test's invites never reach another's."""
    _run_tag[0] = uuid.uuid4().hex[:8]
    yield


def address(name: str) -> str:
    return f"{name}-{_run_tag[0]}@example.com"


async def sign_up(make_client: MakeClient, name: str, email: str) -> httpx.AsyncClient:
    http = make_client()
    await register(http, displayName=name, email=email)
    return http


def friend_names(response: httpx.Response) -> list[str]:
    return [friend["name"] for friend in response.json()]


async def test_a_friend_needs_only_a_name_and_names_are_trimmed(client: httpx.AsyncClient) -> None:
    await register(client)
    created = await client.post(FRIENDS, json={"name": "  Jaymin  "})
    assert created.status_code == 201, created.text
    friend = created.json()
    assert friend["name"] == "Jaymin"
    assert friend["email"] is None
    assert friend["isLinked"] is False
    assert friend["inviteStatus"] is None
    assert {"id", "createdAt", "updatedAt"} <= friend.keys()
    assert friend_names(await client.get(FRIENDS)) == ["Jaymin"]


async def test_friend_names_must_be_present_and_not_too_long(client: httpx.AsyncClient) -> None:
    await register(client)
    for name in ("   ", "x" * 81):
        assert (await client.post(FRIENDS, json={"name": name})).status_code == 422, name
    assert (await client.post(FRIENDS, json={"name": "Riya", "email": "nope"})).status_code == 422
    assert (await client.get(FRIENDS)).json() == []


async def test_two_friends_may_share_a_name_but_not_an_email(client: httpx.AsyncClient) -> None:
    await register(client)
    await client.post(FRIENDS, json={"name": "Jaymin", "email": "j1@example.com"})
    second = await client.post(FRIENDS, json={"name": "Jaymin", "email": "j2@example.com"})
    assert second.status_code == 201

    repeated = await client.post(FRIENDS, json={"name": "Jay", "email": " J1@Example.com "})
    assert repeated.status_code == 409
    assert repeated.json()["error"]["code"] == "friend_email_exists"
    assert len((await client.get(FRIENDS)).json()) == 2


async def test_a_user_cannot_add_themselves_as_a_friend(client: httpx.AsyncClient) -> None:
    await register(client, email="me@example.com")
    response = await client.post(FRIENDS, json={"name": "Me", "email": "ME@example.com"})
    assert response.status_code == 422
    assert response.json()["error"]["details"]["field"] == "email"
    assert (await client.get(FRIENDS)).json() == []


async def test_a_friend_can_be_renamed_and_given_or_changed_an_email(
    client: httpx.AsyncClient,
) -> None:
    await register(client)
    friend = (await client.post(FRIENDS, json={"name": "Jaymin"})).json()
    path = f"{FRIENDS}/{friend['id']}"

    renamed = await client.patch(path, json={"name": "Jay"})
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["name"], renamed.json()["email"]) == ("Jay", None)

    with_email = await client.patch(path, json={"email": "Jay@Example.com"})
    assert with_email.json()["email"] == "jay@example.com"
    assert with_email.json()["name"] == "Jay"

    cleared = await client.patch(path, json={"email": None})
    assert cleared.json()["email"] is None
    assert (await client.patch(path, json={"colour": "red"})).status_code == 422


async def test_a_friend_removed_is_gone_from_the_list(client: httpx.AsyncClient) -> None:
    await register(client)
    friend = (await client.post(FRIENDS, json={"name": "Jaymin"})).json()
    path = f"{FRIENDS}/{friend['id']}"
    assert (await client.delete(path)).status_code == 204
    assert (await client.get(FRIENDS)).json() == []
    assert (await client.delete(path)).status_code == 404


async def test_adding_a_friend_whose_email_has_an_account_sends_them_an_invite(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    jaymin = await sign_up(make_client, "Jaymin Shah", address("jaymin"))

    added = await mitesh.post(FRIENDS, json={"name": "Jaymin", "email": address("jaymin")})
    assert added.json()["inviteStatus"] == "pending"
    assert added.json()["isLinked"] is False

    [invite] = (await jaymin.get(INVITES)).json()
    assert invite["fromName"] == "Mitesh"
    assert invite["fromEmail"] == address("mitesh")
    assert (await mitesh.get(INVITES)).json() == []  # invites are for the invited, not the inviter


async def test_an_invite_to_an_email_with_no_account_waits_for_the_sign_up(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    await mitesh.post(FRIENDS, json={"name": "Riya", "email": address("riya")})

    riya = await sign_up(make_client, "Riya", address("riya").title())
    [invite] = (await riya.get(INVITES)).json()
    assert invite["fromName"] == "Mitesh"


async def test_accepting_an_invite_links_both_users_to_each_other(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    jaymin = await sign_up(make_client, "Jaymin", address("jaymin"))
    await mitesh.post(FRIENDS, json={"name": "Jay", "email": address("jaymin")})
    [invite] = (await jaymin.get(INVITES)).json()

    accepted = await jaymin.post(f"{INVITES}/{invite['id']}/accept")
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["name"] == "Mitesh"
    assert accepted.json()["isLinked"] is True

    [mitesh_sees] = (await mitesh.get(FRIENDS)).json()
    assert (mitesh_sees["name"], mitesh_sees["isLinked"]) == ("Jay", True)
    assert mitesh_sees["inviteStatus"] is None
    [jaymin_sees] = (await jaymin.get(FRIENDS)).json()
    assert (jaymin_sees["name"], jaymin_sees["email"]) == ("Mitesh", address("mitesh"))
    assert (await jaymin.get(INVITES)).json() == []
    assert (await jaymin.post(f"{INVITES}/{invite['id']}/accept")).status_code == 404


async def test_accepting_links_an_existing_friend_with_the_inviters_email(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    jaymin = await sign_up(make_client, "Jaymin", address("jaymin"))
    mine = (await jaymin.post(FRIENDS, json={"name": "Mitu", "email": address("mitesh")})).json()
    await mitesh.post(FRIENDS, json={"name": "Jay", "email": address("jaymin")})
    invites = (await jaymin.get(INVITES)).json()
    assert len(invites) == 1  # his own invite to Mitesh is Mitesh's to answer, not his

    accepted = await jaymin.post(f"{INVITES}/{invites[0]['id']}/accept")
    assert accepted.json()["id"] == mine["id"]  # his own row for Mitesh, now linked
    assert accepted.json()["name"] == "Mitu"
    assert len((await jaymin.get(FRIENDS)).json()) == 1
    # His pending invite to Mitesh is now pointless: they are already linked.
    assert (await mitesh.get(INVITES)).json() == []


async def test_declining_leaves_the_inviters_friend_unlinked(make_client: MakeClient) -> None:
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    jaymin = await sign_up(make_client, "Jaymin", address("jaymin"))
    await mitesh.post(FRIENDS, json={"name": "Jay", "email": address("jaymin")})
    [invite] = (await jaymin.get(INVITES)).json()

    assert (await jaymin.post(f"{INVITES}/{invite['id']}/decline")).status_code == 204
    assert (await jaymin.get(INVITES)).json() == []
    assert (await jaymin.get(FRIENDS)).json() == []
    [kept] = (await mitesh.get(FRIENDS)).json()
    assert (kept["name"], kept["isLinked"], kept["inviteStatus"]) == ("Jay", False, "declined")


async def test_changing_a_friends_email_replaces_the_pending_invite(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    jaymin = await sign_up(make_client, "Jaymin", address("jaymin"))
    riya = await sign_up(make_client, "Riya", address("riya"))
    friend = (await mitesh.post(FRIENDS, json={"name": "J", "email": address("jaymin")})).json()

    await mitesh.patch(f"{FRIENDS}/{friend['id']}", json={"email": address("riya")})
    assert (await jaymin.get(INVITES)).json() == []
    assert len((await riya.get(INVITES)).json()) == 1


async def test_a_linked_friends_email_cannot_be_changed_or_cleared(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    jaymin = await sign_up(make_client, "Jaymin", address("jaymin"))
    friend = (await mitesh.post(FRIENDS, json={"name": "J", "email": address("jaymin")})).json()
    [invite] = (await jaymin.get(INVITES)).json()
    await jaymin.post(f"{INVITES}/{invite['id']}/accept")

    response = await mitesh.patch(f"{FRIENDS}/{friend['id']}", json={"email": "other@example.com"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "friend_linked"
    renamed = await mitesh.patch(f"{FRIENDS}/{friend['id']}", json={"name": "Jay"})
    assert renamed.status_code == 200


async def test_a_third_user_gets_404s_for_other_peoples_friends_and_invites(
    make_client: MakeClient,
) -> None:
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    jaymin = await sign_up(make_client, "Jaymin", address("jaymin"))
    stranger = await sign_up(make_client, "Stranger", address("stranger"))
    friend = (await mitesh.post(FRIENDS, json={"name": "J", "email": address("jaymin")})).json()
    [invite] = (await jaymin.get(INVITES)).json()

    path = f"{FRIENDS}/{friend['id']}"
    assert (await stranger.patch(path, json={"name": "Mine now"})).status_code == 404
    assert (await stranger.delete(path)).status_code == 404
    assert (await stranger.post(f"{INVITES}/{invite['id']}/accept")).status_code == 404
    assert (await stranger.post(f"{INVITES}/{invite['id']}/decline")).status_code == 404
    assert (await mitesh.post(f"{INVITES}/{invite['id']}/accept")).status_code == 404
    assert (await stranger.get(FRIENDS)).json() == []
    assert (await stranger.get(INVITES)).json() == []
    assert (await mitesh.patch(f"{FRIENDS}/{NO_SUCH_ID}", json={"name": "x"})).status_code == 404
    # Nothing the stranger tried changed anything.
    assert friend_names(await mitesh.get(FRIENDS)) == ["J"]
    assert len((await jaymin.get(INVITES)).json()) == 1


async def test_every_friend_and_invite_change_is_audited(app: Any, make_client: MakeClient) -> None:
    mitesh, jaymin = make_client(), make_client()
    people = [
        (await register(mitesh, displayName="Mitesh"))["user"]["id"],
        (await register(jaymin, displayName="Jaymin", email=address("jaymin-audit")))["user"]["id"],
    ]
    friend = (
        await mitesh.post(FRIENDS, json={"name": "J", "email": address("jaymin-audit")})
    ).json()
    await mitesh.patch(f"{FRIENDS}/{friend['id']}", json={"name": "Jay"})
    [invite] = (await jaymin.get(INVITES)).json()
    await jaymin.post(f"{INVITES}/{invite['id']}/accept")
    extra = (await mitesh.post(FRIENDS, json={"name": "Temp"})).json()
    await mitesh.delete(f"{FRIENDS}/{extra['id']}")

    async def actions_for(entity_type: str) -> list[str]:
        async with app.state.container.session_factory() as session:
            return list(
                (
                    await session.scalars(
                        select(AuditEvent.action)
                        .where(
                            AuditEvent.entity_type == entity_type, AuditEvent.user_id.in_(people)
                        )
                        .order_by(AuditEvent.created_at, AuditEvent.id)
                    )
                ).all()
            )

    friend_actions = await actions_for("friend")
    assert friend_actions.count("friend.created") == 3  # J, Temp, and Jaymin's row for Mitesh
    assert "friend.updated" in friend_actions
    assert friend_actions.count("friend.linked") == 2
    assert "friend.removed" in friend_actions
    assert await actions_for("friend_invite") == ["friend_invite.sent", "friend_invite.accepted"]
