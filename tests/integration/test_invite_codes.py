"""Accepting a friend invite needs a one-time code emailed to the invited address, so signing up
with someone's email is not enough to become their friend."""

from __future__ import annotations

from datetime import timedelta

import httpx

from finance_core.clock import FixedClock
from tests.conftest import NOW, OUTBOX, emailed_invite_code
from tests.integration.test_friends import (  # noqa: F401 - the fixture gives each test fresh emails
    FRIENDS,
    INVITES,
    MakeClient,
    _fresh_addresses,
    address,
    sign_up,
)
from tests.integration.test_password_reset import clock_moved_forward


async def invited(make_client: MakeClient) -> tuple[httpx.AsyncClient, httpx.AsyncClient, str]:
    """Mitesh invites Jaymin's address; returns both clients and the invite id."""
    mitesh = await sign_up(make_client, "Mitesh", address("mitesh"))
    jaymin = await sign_up(make_client, "Jaymin", address("jaymin"))
    await mitesh.post(FRIENDS, json={"name": "Jay", "email": address("jaymin")})
    [invite] = (await jaymin.get(INVITES)).json()
    return mitesh, jaymin, invite["id"]


async def accept_with(http: httpx.AsyncClient, invite_id: str, code: str) -> httpx.Response:
    return await http.post(f"{INVITES}/{invite_id}/accept", json={"code": code})


async def is_linked(http: httpx.AsyncClient) -> bool:
    return any(friend["isLinked"] for friend in (await http.get(FRIENDS)).json())


async def test_an_invite_cannot_be_accepted_without_proving_the_email(
    make_client: MakeClient,
) -> None:
    mitesh, jaymin, invite_id = await invited(make_client)

    no_code = await jaymin.post(f"{INVITES}/{invite_id}/accept")
    guessed = await accept_with(jaymin, invite_id, "123456")

    assert no_code.status_code == 422
    assert guessed.status_code == 422
    assert not await is_linked(mitesh)
    assert len((await jaymin.get(INVITES)).json()) == 1


async def test_the_code_is_emailed_to_the_invited_address_only(make_client: MakeClient) -> None:
    _mitesh, jaymin, invite_id = await invited(make_client)

    asked = await jaymin.post(f"{INVITES}/{invite_id}/code")

    assert asked.status_code == 202
    assert asked.json() == {"email": address("jaymin")}
    assert OUTBOX.to(address("jaymin"))[-1].subject.startswith("Your MoneyMoney")
    assert OUTBOX.to(address("mitesh")) == []


async def test_a_wrong_code_changes_nothing(make_client: MakeClient) -> None:
    mitesh, jaymin, invite_id = await invited(make_client)
    code = await emailed_invite_code(jaymin, invite_id)
    wrong = "000000" if code != "000000" else "111111"

    rejected = await accept_with(jaymin, invite_id, wrong)

    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "invite_code_invalid"
    assert not await is_linked(mitesh)
    assert (await jaymin.get(FRIENDS)).json() == []
    assert len((await jaymin.get(INVITES)).json()) == 1


async def test_an_expired_code_changes_nothing(make_client: MakeClient, clock: FixedClock) -> None:
    mitesh, jaymin, invite_id = await invited(make_client)
    code = await emailed_invite_code(jaymin, invite_id)

    with clock_moved_forward(clock, timedelta(minutes=16)):
        rejected = await accept_with(jaymin, invite_id, code)

    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "invite_code_invalid"
    assert not await is_linked(mitesh)
    assert clock.now() == NOW


async def test_the_right_code_links_once(make_client: MakeClient) -> None:
    mitesh, jaymin, invite_id = await invited(make_client)
    code = await emailed_invite_code(jaymin, invite_id)

    accepted = await accept_with(jaymin, invite_id, code)
    again = await accept_with(jaymin, invite_id, code)

    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["isLinked"] is True
    assert again.status_code == 404  # the invite is answered; it cannot link twice
    assert await is_linked(mitesh)
    assert len((await jaymin.get(FRIENDS)).json()) == 1


async def test_a_newer_code_replaces_the_older_one(make_client: MakeClient) -> None:
    _mitesh, jaymin, invite_id = await invited(make_client)
    first = await emailed_invite_code(jaymin, invite_id)
    second = await emailed_invite_code(jaymin, invite_id)

    if first != second:  # a repeat of the same six digits would prove nothing
        assert (await accept_with(jaymin, invite_id, first)).status_code == 422
    assert (await accept_with(jaymin, invite_id, second)).status_code == 200


async def test_too_many_wrong_codes_burn_the_code(make_client: MakeClient) -> None:
    mitesh, jaymin, invite_id = await invited(make_client)
    code = await emailed_invite_code(jaymin, invite_id)
    wrong = "000000" if code != "000000" else "111111"

    for _ in range(5):
        assert (await accept_with(jaymin, invite_id, wrong)).status_code == 422
    right_but_late = await accept_with(jaymin, invite_id, code)

    assert right_but_late.status_code == 422
    assert not await is_linked(mitesh)
    fresh = await emailed_invite_code(jaymin, invite_id)
    assert (await accept_with(jaymin, invite_id, fresh)).status_code == 200


async def test_someone_elses_invite_gets_no_code(make_client: MakeClient) -> None:
    _mitesh, _jaymin, invite_id = await invited(make_client)
    stranger = await sign_up(make_client, "Stranger", address("stranger"))

    assert (await stranger.post(f"{INVITES}/{invite_id}/code")).status_code == 404
    assert (await accept_with(stranger, invite_id, "123456")).status_code == 404


async def test_asking_for_codes_over_and_over_is_rate_limited(make_client: MakeClient) -> None:
    _mitesh, jaymin, invite_id = await invited(make_client)

    statuses = [(await jaymin.post(f"{INVITES}/{invite_id}/code")).status_code for _ in range(7)]

    assert statuses[:5] == [202] * 5
    assert statuses[-1] == 429
