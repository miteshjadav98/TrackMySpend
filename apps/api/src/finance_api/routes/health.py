from __future__ import annotations

import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from finance_api.deps import ContainerDep

router = APIRouter(tags=["health"])


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. Never touches dependencies."""
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readyz(container: ContainerDep) -> JSONResponse:
    """Readiness: Postgres is required; Redis is optional (degraded, still serving)."""
    checks: dict[str, str] = {}
    try:
        async with asyncio.timeout(2):
            async with container.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    checks["redis"] = "ok" if await container.redis.ping() else "degraded"
    database_ok = checks["database"] == "ok"
    status = (
        "ok"
        if database_ok and checks["redis"] == "ok"
        else ("degraded" if database_ok else "unavailable")
    )
    return JSONResponse(
        {"status": status, "checks": checks}, status_code=200 if database_ok else 503
    )
