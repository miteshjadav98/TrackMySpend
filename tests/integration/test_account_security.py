"""Account security: signed-in sessions and changing the password."""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import ANY

import httpx
import pytest
from sqlalchemy import select

from finance_core.audit.models import AuditEvent
from finance_core.config import Settings
from tests.conftest import register

SESSIONS = "/api/v1/auth/sessions"
PASSWORD = "/api/v1/auth/password"
ORIGIN = "http://localhost:3000"
SIGNUP_PASSWORD = "correct-horse-battery"  # what conftest.register() signs up with
CHROME_ON_WINDOWS = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


async def sign_in(http: httpx.AsyncClient, email: str, password: str = SIGNUP_PASSWORD) -> None:
    response = await http.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


async def sessions_of(http: httpx.AsyncClient) -> list[dict[str, Any]]:
    response = await http.get(SESSIONS)
    assert response.status_code == 200, response.text
    return response.json()  # type: ignore[no-any-return]


async def test_sessions_list_every_signed_in_device_with_this_device_first(make_client) -> None:  # type: ignore[no-untyped-def]
    laptop, script = make_client(), make_client()
    laptop.headers["User-Agent"] = CHROME_ON_WINDOWS
    me = await register(laptop)
    await sign_in(script, me["user"]["email"])  # httpx's own User-Agent

    from_script = await sessions_of(script)
    from_laptop = await sessions_of(laptop)

    assert [(s["device"], s["isCurrent"]) for s in from_script] == [
        ("API client", True),
        ("Chrome on Windows", False),
    ]
    assert [(s["device"], s["isCurrent"]) for s in from_laptop] == [
        ("Chrome on Windows", True),
        ("API client", False),
    ]
    session = from_script[0]
    assert set(session) == {"id", "device", "ipAddress", "createdAt", "lastSeenAt", "isCurrent"}
    assert session["ipAddress"] == "127.0.0.1"
    assert session["lastSeenAt"] == "2026-10-24T06:30:00Z"  # the test clock's "now"


async def test_signing_out_another_device_ends_its_session_at_once(make_client) -> None:  # type: ignore[no-untyped-def]
    laptop, lost_phone = make_client(), make_client()
    me = await register(laptop)
    await sign_in(lost_phone, me["user"]["email"])
    phone_session = (await sessions_of(laptop))[1]

    response = await laptop.delete(f"{SESSIONS}/{phone_session['id']}")

    assert response.status_code == 204
    revoked = await lost_phone.get("/api/v1/me")
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "session_expired"
    assert (await laptop.get("/api/v1/me")).status_code == 200
    assert [s["isCurrent"] for s in await sessions_of(laptop)] == [True]


async def test_signing_out_this_device_works_like_logout(client: httpx.AsyncClient) -> None:
    await register(client)
    token = client.cookies.get("mm_session")
    this_device = (await sessions_of(client))[0]

    response = await client.delete(f"{SESSIONS}/{this_device['id']}")

    assert response.status_code == 204
    assert "mm_session" not in client.cookies  # the browser drops its cookie
    still_valid = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert still_valid.status_code == 401  # and the token itself no longer works


async def test_another_users_or_an_unknown_session_cannot_be_signed_out(make_client) -> None:  # type: ignore[no-untyped-def]
    alice, bob = make_client(), make_client()
    await register(alice)
    await register(bob)
    alices_session = (await sessions_of(alice))[0]["id"]

    by_bob = await bob.delete(f"{SESSIONS}/{alices_session}")
    unknown = await bob.delete(f"{SESSIONS}/{uuid.uuid4()}")

    assert by_bob.status_code == 404 and unknown.status_code == 404
    assert by_bob.json()["error"] == {**unknown.json()["error"], "requestId": ANY}
    assert (await alice.get("/api/v1/me")).status_code == 200
    assert alices_session not in {s["id"] for s in await sessions_of(bob)}


async def test_signing_out_all_other_devices_leaves_only_this_one(make_client) -> None:  # type: ignore[no-untyped-def]
    laptop, phone, tablet = make_client(), make_client(), make_client()
    me = await register(laptop)
    await sign_in(phone, me["user"]["email"])
    await sign_in(tablet, me["user"]["email"])

    response = await laptop.post(f"{SESSIONS}/revoke-others")

    assert response.status_code == 200
    assert response.json() == {"revoked": 2}
    assert (await phone.get("/api/v1/me")).status_code == 401
    assert (await tablet.get("/api/v1/me")).status_code == 401
    assert (await laptop.get("/api/v1/me")).status_code == 200
    assert [s["isCurrent"] for s in await sessions_of(laptop)] == [True]
    again = await laptop.post(f"{SESSIONS}/revoke-others")
    assert again.json() == {"revoked": 0}


async def test_a_password_change_names_the_field_that_is_wrong(client: httpx.AsyncClient) -> None:
    await register(client)

    async def rejected_field(current: str, new: str) -> str:
        response = await client.post(
            PASSWORD, json={"currentPassword": current, "newPassword": new}
        )
        assert response.status_code == 422, response.text
        assert current not in response.text and new not in response.text  # never echoed
        return str(response.json()["error"]["details"]["field"])

    assert await rejected_field("not-my-password", "a-brand-new-password") == "currentPassword"
    assert await rejected_field(SIGNUP_PASSWORD, "too-short") == "newPassword"
    assert await rejected_field(SIGNUP_PASSWORD, SIGNUP_PASSWORD) == "newPassword"
    assert (await client.get("/api/v1/me")).status_code == 200  # nothing changed


async def test_changing_the_password_signs_out_every_other_device(make_client) -> None:  # type: ignore[no-untyped-def]
    laptop, phone = make_client(), make_client()
    me = await register(laptop)
    email = me["user"]["email"]
    await sign_in(phone, email)

    response = await laptop.post(
        PASSWORD,
        json={"currentPassword": SIGNUP_PASSWORD, "newPassword": "a-brand-new-password"},
    )

    assert response.status_code == 204
    assert (await phone.get("/api/v1/me")).status_code == 401
    assert (await laptop.get("/api/v1/me")).status_code == 200
    old = await make_client().post(
        "/api/v1/auth/login", json={"email": email, "password": SIGNUP_PASSWORD}
    )
    assert old.status_code == 401
    await sign_in(make_client(), email, "a-brand-new-password")


async def test_password_guesses_are_rate_limited_like_login(
    app: Any, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_login_per_minute", 2)
    # Its own client address, so other tests' attempts from the shared address don't count.
    transport = httpx.ASGITransport(app=app, client=("203.0.113.40", 50000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver", headers={"Origin": ORIGIN}
    ) as guesser:
        await register(guesser)
        for guess in ("guess-number-one", "guess-number-two"):
            wrong = await guesser.post(
                PASSWORD, json={"currentPassword": guess, "newPassword": "a-brand-new-password"}
            )
            assert wrong.status_code == 422

        blocked = await guesser.post(
            PASSWORD,
            json={"currentPassword": SIGNUP_PASSWORD, "newPassword": "a-brand-new-password"},
        )

    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["Retry-After"]) >= 1


async def test_every_security_change_is_audited(app: Any, make_client) -> None:  # type: ignore[no-untyped-def]
    laptop, phone, tablet = make_client(), make_client(), make_client()
    me = await register(laptop)
    await sign_in(phone, me["user"]["email"])
    phone_session = (await sessions_of(phone))[0]["id"]
    await sign_in(tablet, me["user"]["email"])

    await laptop.delete(f"{SESSIONS}/{phone_session}")
    await laptop.post(f"{SESSIONS}/revoke-others")  # signs the tablet out
    await laptop.post(
        PASSWORD,
        json={"currentPassword": SIGNUP_PASSWORD, "newPassword": "a-brand-new-password"},
    )

    async with app.state.container.session_factory() as session:
        events = (
            await session.execute(
                select(AuditEvent.action, AuditEvent.entity_id, AuditEvent.data)
                .where(
                    AuditEvent.user_id == me["user"]["id"],
                    AuditEvent.action.in_(
                        [
                            "auth.session_revoked",
                            "auth.other_sessions_revoked",
                            "auth.password_changed",
                        ]
                    ),
                )
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
    assert [(action, data) for action, _, data in events] == [
        ("auth.session_revoked", {"thisDevice": False}),
        ("auth.other_sessions_revoked", {"revoked": 1}),
        ("auth.password_changed", {"otherSessionsRevoked": 0}),
    ]
    assert str(events[0].entity_id) == phone_session
