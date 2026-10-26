"""Shared fixtures.

Unit tests need nothing running. Integration tests use the docker compose Postgres (a
separate `moneymoney_test` database) and Redis (db 1); they are skipped with a clear
message when those are unreachable.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from finance_core.clock import FixedClock
from finance_core.config import Settings
from finance_core.llm.base import ReplyRequest, UnderstandRequest, UnderstandResult
from finance_core.llm.rules import RulesLLMClient

ROOT = Path(__file__).resolve().parents[1]

# Saturday 24 Oct 2026, 12:00 in Asia/Kolkata. Every date assertion is relative to this.
NOW = datetime(2026, 10, 24, 6, 30, tzinfo=UTC)

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://moneymoney:moneymoney@localhost:5432/moneymoney_test"
)
TEST_REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/1")


if sys.platform == "win32":
    # psycopg's async driver needs a selector loop on Windows.
    def pytest_asyncio_loop_factories(config: Any, item: Any) -> dict[str, Any]:
        return {"selector": asyncio.SelectorEventLoop}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        if "/integration/" in item.nodeid.replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


# ---------------------------------------------------------------------------------------
# Settings, clock, LLM
# ---------------------------------------------------------------------------------------


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "environment": "test",
        "database_url": TEST_DATABASE_URL,
        "redis_url": TEST_REDIS_URL,
        "redis_key_prefix": "mmtest",
        "llm_provider": "rules",
        "cookie_secure": False,
        "allowed_origins": ["http://localhost:3000"],
        "log_json": False,
        "log_level": "WARNING",
        # Tests register many users from one IP; rate limits get their own tests.
        "rate_limit_login_per_minute": 1000,
        "rate_limit_register_per_hour": 10_000,
        "rate_limit_chat_per_minute": 1000,
        "rate_limit_chat_per_day": 100_000,
        "database_pool_size": 5,
        "database_max_overflow": 5,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class SwitchableLLM:
    """Delegates to the rules engine; a test can swap in a scripted or failing client."""

    name = "switchable"

    def __init__(self) -> None:
        self.delegate: Any = RulesLLMClient()

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        result: UnderstandResult = await self.delegate.understand(request)
        return result

    def stream_reply(self, request: ReplyRequest) -> Any:
        return self.delegate.stream_reply(request)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return make_settings()


@pytest.fixture(scope="session")
def clock() -> FixedClock:
    return FixedClock(NOW)


@pytest.fixture(scope="session")
def llm() -> SwitchableLLM:
    return SwitchableLLM()


@pytest.fixture(autouse=True)
def _reset_llm(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if "llm" in request.fixturenames:
        request.getfixturevalue("llm").delegate = RulesLLMClient()


# ---------------------------------------------------------------------------------------
# Infrastructure (integration tests only)
# ---------------------------------------------------------------------------------------


def _reachable() -> str | None:
    try:
        import psycopg
        import redis

        psycopg.connect(TEST_DATABASE_URL, connect_timeout=3).close()
        redis.Redis.from_url(TEST_REDIS_URL, socket_timeout=2).ping()
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


@pytest.fixture(scope="session")
def prepared_database(settings: Settings) -> None:
    """Fresh schema per test session: drop everything, then run the real deploy migration."""
    problem = _reachable()
    if problem:
        message = f"integration services unavailable (run `docker compose up -d`): {problem}"
        if os.environ.get("CI"):  # in CI a skipped integration suite must not pass as green
            pytest.fail(message)
        pytest.skip(message)
    import psycopg
    import redis

    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as connection:
        for schema in ("identity", "ledger", "chat", "audit", "agent"):
            connection.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        connection.execute("DROP TABLE IF EXISTS public.alembic_version")
    env = {
        **os.environ,
        "DATABASE_URL": TEST_DATABASE_URL,
        "ENVIRONMENT": "test",
        "PYTHONUTF8": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-m", "finance_core.manage", "migrate"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(f"migration failed:\n{completed.stdout}\n{completed.stderr}")
    redis.Redis.from_url(TEST_REDIS_URL).flushdb()


@pytest.fixture(scope="session")
async def app(
    prepared_database: None, settings: Settings, llm: SwitchableLLM, clock: FixedClock
) -> AsyncIterator[Any]:
    from finance_api.main import create_app

    application = create_app(settings, llm=llm, clock=clock)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    """A fresh browser-like client (own cookie jar) per test."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost:3000"},
    ) as http:
        yield http


@pytest.fixture
async def make_client(app: Any) -> AsyncIterator[Any]:
    clients: list[httpx.AsyncClient] = []

    def factory() -> httpx.AsyncClient:
        http = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            headers={"Origin": "http://localhost:3000"},
        )
        clients.append(http)
        return http

    yield factory
    for http in clients:
        await http.aclose()


# ---------------------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------------------


async def register(http: httpx.AsyncClient, **overrides: Any) -> dict[str, Any]:
    body = {
        "email": f"user-{uuid.uuid4().hex[:10]}@example.com",
        "password": "correct-horse-battery",
        "displayName": "Test User",
        **overrides,
    }
    response = await http.post("/api/v1/auth/register", json=body)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def new_conversation(http: httpx.AsyncClient) -> str:
    response = await http.post("/api/v1/conversations", json={})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def say(
    http: httpx.AsyncClient,
    conversation_id: str,
    text: str | None = None,
    *,
    answer: dict[str, Any] | None = None,
    client_message_id: str | None = None,
    expect: int = 200,
) -> dict[str, Any]:
    payload: dict[str, Any]
    if answer is not None:
        payload = {"type": "interaction_response", **answer}
    else:
        payload = {"type": "text", "text": text}
    response = await http.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"clientMessageId": client_message_id or str(uuid.uuid4()), "input": payload},
    )
    assert response.status_code == expect, response.text
    return response.json()  # type: ignore[no-any-return]


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name, data = None, []
        for line in block.split("\n"):
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data.append(line[len("data: ") :])
        if name and data:
            events.append((name, json.loads("\n".join(data))))
    return events
