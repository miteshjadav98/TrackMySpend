"""Password reset: a single-use, short-lived link emailed to a user who forgot their password."""

from __future__ import annotations

import asyncio
import hashlib
import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import or_, select, update

from finance_core.audit.models import AuditEvent
from finance_core.auth.models import PasswordResetToken
from finance_core.clock import FixedClock
from finance_core.config import Settings
from finance_core.email_sender import EmailMessage
from finance_core.users.models import User
from tests.conftest import NOW, Outbox, register

RESET = "/api/v1/auth/password-reset"
CONFIRM = "/api/v1/auth/password-reset/confirm"
RESET_LINK = re.compile(r"(?P<page>\S+/reset-password)#token=(?P<token>[\w-]+)")
OLD_PASSWORD = "correct-horse-battery"  # what conftest.register() signs up with
NEW_PASSWORD = "a-brand-new-password"


async def emails_to(app: Any, outbox: Outbox, address: str) -> list[EmailMessage]:
    """Emails sent to `address`, once the app has finished the work it does after replying."""
    await asyncio.gather(*app.state.container.background)
    return outbox.to(address)


async def emailed_token(app: Any, outbox: Outbox, http: httpx.AsyncClient, email: str) -> str:
    """Ask for a reset link for `email` and return the token from the email it sends."""
    response = await http.post(RESET, json={"email": email})
    assert response.status_code == 202, response.text
    latest = (await emails_to(app, outbox, email))[-1]
    link = RESET_LINK.search(latest.text)
    assert link is not None, latest.text
    return link["token"]


async def log_in(http: httpx.AsyncClient, email: str, password: str) -> httpx.Response:
    return await http.post("/api/v1/auth/login", json={"email": email, "password": password})


def assert_link_rejected(response: httpx.Response) -> None:
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "reset_link_invalid"
    assert "request a new one" in error["message"].lower()


@contextmanager
def clock_moved_forward(clock: FixedClock, by: timedelta) -> Iterator[None]:
    # The test clock is shared by the whole session, so put it back for the next test.
    clock.set(NOW + by)
    try:
        yield
    finally:
        clock.set(NOW)


async def request_reset_from(app: Any, ip_address: str, email: str) -> httpx.Response:
    """Ask for a reset link from a client at `ip_address`, so other tests' requests don't count."""
    transport = httpx.ASGITransport(app=app, client=(ip_address, 50000))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
        return await http.post(RESET, json={"email": email})


async def disable_account(app: Any, email: str) -> None:
    # There is no API for disabling an account yet, so the test does it in the database.
    async with app.state.container.session_factory() as session:
        await session.execute(update(User).where(User.email == email).values(status="disabled"))
        await session.commit()


async def test_a_reset_request_emails_a_link_to_the_reset_page(
    app: Any, outbox: Outbox, make_client: Any
) -> None:
    me = await register(make_client())
    email = me["user"]["email"]

    response = await make_client().post(RESET, json={"email": email})

    assert response.status_code == 202
    [message] = await emails_to(app, outbox, email)
    link = RESET_LINK.search(message.text)
    assert link is not None, message.text
    assert link["page"] == "http://localhost:3000/reset-password"


async def test_a_reset_link_sets_a_new_password_and_signs_out_every_device(
    app: Any, outbox: Outbox, make_client: Any
) -> None:
    laptop, phone = make_client(), make_client()
    me = await register(laptop)
    email = me["user"]["email"]
    assert (await log_in(phone, email, OLD_PASSWORD)).status_code == 200
    laptop_token = laptop.cookies["mm_session"]
    token = await emailed_token(app, outbox, make_client(), email)

    # The user opens the emailed link on the laptop, which is still signed in.
    response = await laptop.post(CONFIRM, json={"token": token, "newPassword": NEW_PASSWORD})

    assert response.status_code == 204
    assert "mm_session" not in laptop.cookies  # the browser drops its now-dead session
    laptop_session = {"Authorization": f"Bearer {laptop_token}"}
    assert (await make_client().get("/api/v1/me", headers=laptop_session)).status_code == 401
    assert (await phone.get("/api/v1/me")).status_code == 401
    assert (await log_in(make_client(), email, OLD_PASSWORD)).status_code == 401
    assert (await log_in(make_client(), email, NEW_PASSWORD)).status_code == 200


async def test_the_reply_never_reveals_whether_an_account_exists(
    app: Any, outbox: Outbox, make_client: Any
) -> None:
    active = (await register(make_client()))["user"]["email"]
    disabled = (await register(make_client()))["user"]["email"]
    await disable_account(app, disabled)
    unknown = f"nobody-{uuid.uuid4().hex[:10]}@example.com"

    replies = [
        await make_client().post(RESET, json={"email": e}) for e in (active, disabled, unknown)
    ]

    assert [reply.status_code for reply in replies] == [202, 202, 202]
    assert replies[0].json() == replies[1].json() == replies[2].json()
    assert len(await emails_to(app, outbox, active)) == 1
    assert await emails_to(app, outbox, disabled) == []
    assert await emails_to(app, outbox, unknown) == []


async def test_a_reset_link_works_only_once(app: Any, outbox: Outbox, make_client: Any) -> None:
    email = (await register(make_client()))["user"]["email"]
    token = await emailed_token(app, outbox, make_client(), email)
    first = await make_client().post(CONFIRM, json={"token": token, "newPassword": NEW_PASSWORD})

    again = await make_client().post(
        CONFIRM, json={"token": token, "newPassword": "someone-elses-password"}
    )

    assert first.status_code == 204
    assert_link_rejected(again)
    assert (await log_in(make_client(), email, NEW_PASSWORD)).status_code == 200


async def test_a_reset_link_expires_after_30_minutes(
    app: Any, outbox: Outbox, clock: FixedClock, make_client: Any
) -> None:
    email = (await register(make_client()))["user"]["email"]
    token = await emailed_token(app, outbox, make_client(), email)

    with clock_moved_forward(clock, by=timedelta(minutes=31)):
        late = await make_client().post(CONFIRM, json={"token": token, "newPassword": NEW_PASSWORD})

    assert_link_rejected(late)
    assert (await log_in(make_client(), email, OLD_PASSWORD)).status_code == 200


async def test_a_made_up_reset_link_is_rejected(client: httpx.AsyncClient) -> None:
    response = await client.post(
        CONFIRM, json={"token": "not-a-token-we-ever-sent", "newPassword": NEW_PASSWORD}
    )

    assert_link_rejected(response)


async def test_a_new_reset_link_replaces_the_earlier_one(
    app: Any, outbox: Outbox, make_client: Any
) -> None:
    email = (await register(make_client()))["user"]["email"]
    earlier = await emailed_token(app, outbox, make_client(), email)
    later = await emailed_token(app, outbox, make_client(), email)

    with_earlier = await make_client().post(
        CONFIRM, json={"token": earlier, "newPassword": NEW_PASSWORD}
    )
    with_later = await make_client().post(
        CONFIRM, json={"token": later, "newPassword": NEW_PASSWORD}
    )

    assert_link_rejected(with_earlier)
    assert with_later.status_code == 204


async def test_a_too_short_new_password_is_refused_without_using_up_the_link(
    app: Any, outbox: Outbox, make_client: Any
) -> None:
    email = (await register(make_client()))["user"]["email"]
    token = await emailed_token(app, outbox, make_client(), email)

    too_short = await make_client().post(CONFIRM, json={"token": token, "newPassword": "short"})
    retried = await make_client().post(CONFIRM, json={"token": token, "newPassword": NEW_PASSWORD})

    assert too_short.status_code == 422
    assert too_short.json()["error"]["details"]["field"] == "newPassword"
    assert retried.status_code == 204


async def test_only_the_sha256_of_a_reset_token_is_stored(
    app: Any, outbox: Outbox, make_client: Any
) -> None:
    me = await register(make_client())
    token = await emailed_token(app, outbox, make_client(), me["user"]["email"])

    async with app.state.container.session_factory() as session:
        [stored] = (
            await session.scalars(
                select(PasswordResetToken).where(PasswordResetToken.user_id == me["user"]["id"])
            )
        ).all()
    assert stored.token_hash == hashlib.sha256(token.encode()).digest()
    assert token not in repr(vars(stored))


async def test_reset_requests_and_resets_are_audited_for_real_accounts_only(
    app: Any, outbox: Outbox, make_client: Any
) -> None:
    laptop = make_client()
    me = await register(laptop)
    token = await emailed_token(app, outbox, make_client(), me["user"]["email"])
    await make_client().post(CONFIRM, json={"token": token, "newPassword": NEW_PASSWORD})
    unknown = f"nobody-{uuid.uuid4().hex[:10]}@example.com"
    await make_client().post(RESET, json={"email": unknown})
    assert await emails_to(app, outbox, unknown) == []  # waits for the work after the reply

    async with app.state.container.session_factory() as session:
        events = (
            await session.execute(
                select(AuditEvent.user_id, AuditEvent.action, AuditEvent.data)
                .where(AuditEvent.action.like("auth.password_reset%"))
                .where(or_(AuditEvent.user_id == me["user"]["id"], AuditEvent.user_id.is_(None)))
                .order_by(AuditEvent.created_at, AuditEvent.id)
            )
        ).all()
    assert [(action, data) for _, action, data in events] == [
        ("auth.password_reset_requested", None),
        ("auth.password_reset", {"sessionsRevoked": 1}),  # the laptop
    ]


async def test_reset_requests_for_one_email_are_rate_limited_from_any_address(
    app: Any, settings: Settings, monkeypatch: pytest.MonkeyPatch, make_client: Any
) -> None:
    monkeypatch.setattr(settings, "rate_limit_password_reset_per_email_per_hour", 2)
    email = (await register(make_client()))["user"]["email"]

    allowed = [
        await request_reset_from(app, "203.0.113.50", email),
        await request_reset_from(app, "203.0.113.51", email),
    ]
    blocked = await request_reset_from(app, "203.0.113.52", email)

    assert [response.status_code for response in allowed] == [202, 202]
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"


async def test_reset_requests_from_one_address_are_rate_limited_across_emails(
    app: Any, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "rate_limit_password_reset_per_ip_per_hour", 2)
    emails = [f"someone-{uuid.uuid4().hex[:10]}@example.com" for _ in range(3)]

    responses = [await request_reset_from(app, "203.0.113.60", email) for email in emails]

    assert [response.status_code for response in responses] == [202, 202, 429]


class StuckEmailProvider:
    """An email provider that does not answer until the test lets it."""

    def __init__(self) -> None:
        self.answer = asyncio.Event()
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        await self.answer.wait()
        self.sent.append(message)


async def test_the_reply_does_not_wait_for_the_email_to_be_sent(
    app: Any, monkeypatch: pytest.MonkeyPatch, make_client: Any
) -> None:
    email = (await register(make_client()))["user"]["email"]
    stuck = StuckEmailProvider()
    monkeypatch.setattr(app.state.container, "email_sender", stuck)

    response = await asyncio.wait_for(make_client().post(RESET, json={"email": email}), 5)

    assert response.status_code == 202
    assert stuck.sent == []
    stuck.answer.set()
    await asyncio.gather(*app.state.container.background)
    assert [message.to for message in stuck.sent] == [email]
