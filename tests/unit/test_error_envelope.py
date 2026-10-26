"""Transient database failures map to 503 + Retry-After in the standard error envelope."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from finance_api.errors import register_exception_handlers
from finance_api.middleware import RequestContextMiddleware
from tests.conftest import make_settings


def _app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware, settings=make_settings())

    @app.get("/db-down")
    async def db_down() -> None:
        raise OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))

    @app.get("/pool-exhausted")
    async def pool_exhausted() -> None:
        raise PoolTimeoutError("QueuePool limit reached")

    @app.get("/bug")
    async def bug() -> None:
        raise RuntimeError("boom")

    return app


@pytest.mark.parametrize("path", ["/db-down", "/pool-exhausted"])
async def test_database_outage_is_503_with_retry_after(path: str) -> None:
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get(path, headers={"X-Request-ID": "req-12345678"})
    assert response.status_code == 503
    assert response.headers["retry-after"] == "5"
    error = response.json()["error"]
    assert error["code"] == "database_unavailable"
    assert error["requestId"] == "req-12345678"
    assert "connection refused" not in response.text  # driver details never leak


async def test_other_errors_stay_500() -> None:
    transport = httpx.ASGITransport(app=_app(), raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        response = await http.get("/bug")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
