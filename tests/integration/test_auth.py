from __future__ import annotations

import httpx
import pytest

from finance_core.cache import RateLimiter, RedisClient
from finance_core.errors import RateLimitedError
from tests.conftest import make_settings, register


async def test_register_normalises_email_and_sets_a_safe_cookie(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "Mixed.Case@Example.COM",
            "password": "correct-horse-battery",
            "displayName": "Asha",
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["email"] == "mixed.case@example.com"
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie
    me = await client.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["profile"] == {
        "baseCurrency": "INR",
        "timezone": "Asia/Kolkata",
        "locale": "en-IN",
    }


async def test_duplicate_email_is_a_conflict(client: httpx.AsyncClient, make_client) -> None:  # type: ignore[no-untyped-def]
    me = await register(client)
    response = await make_client().post(
        "/api/v1/auth/register",
        json={
            "email": me["user"]["email"].upper(),
            "password": "another-long-password",
            "displayName": "X",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "email_taken"


async def test_password_policy_never_echoes_the_password(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "short@example.com", "password": "hunter2", "displayName": "X"},
    )
    assert response.status_code == 422
    assert "hunter2" not in response.text


async def test_login_logout_and_server_side_revocation(make_client) -> None:  # type: ignore[no-untyped-def]
    first, second = make_client(), make_client()
    me = await register(first)
    email = me["user"]["email"]

    for password in ("wrong-password-123", "another-wrong-one"):
        bad = await second.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert bad.status_code == 401
        assert bad.json()["error"]["code"] == "invalid_credentials"
    unknown = await second.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever-password"}
    )
    assert (
        unknown.json()["error"]["message"] == bad.json()["error"]["message"]
    )  # no account probing

    good = await second.post(
        "/api/v1/auth/login", json={"email": email, "password": "correct-horse-battery"}
    )
    assert good.status_code == 200
    token = second.cookies.get("mm_session")
    assert token

    assert (await second.post("/api/v1/auth/logout")).status_code == 204
    revoked = await make_client().get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "session_expired"
    assert (await first.get("/api/v1/me")).status_code == 200  # other sessions unaffected


async def test_bearer_tokens_work_for_api_clients(client: httpx.AsyncClient, make_client) -> None:  # type: ignore[no-untyped-def]
    await register(client)
    token = client.cookies.get("mm_session")
    api = make_client()
    api.headers.pop("Origin")
    response = await api.post(
        "/api/v1/transactions",
        json={"type": "expense", "amount": "10"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201


async def test_cross_site_writes_are_blocked(client: httpx.AsyncClient) -> None:
    await register(client)
    response = await client.post(
        "/api/v1/conversations", json={}, headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"


async def test_rate_limiter_blocks_then_fails_open() -> None:
    redis = RedisClient.from_settings(make_settings())
    limiter = RateLimiter(redis)
    key = "login-test-account"
    await limiter.hit("t", key, limit=2, window_seconds=60)
    await limiter.hit("t", key, limit=2, window_seconds=60)
    with pytest.raises(RateLimitedError) as excinfo:
        await limiter.hit("t", key, limit=2, window_seconds=60)
    assert excinfo.value.retry_after_seconds >= 1
    await redis.close()

    dead = RedisClient.from_settings(make_settings(redis_url="redis://127.0.0.1:6390/0"))
    for _ in range(5):  # Redis down: requests are allowed, not rejected
        await RateLimiter(dead).hit("t", key, limit=1, window_seconds=60)
    await dead.close()
