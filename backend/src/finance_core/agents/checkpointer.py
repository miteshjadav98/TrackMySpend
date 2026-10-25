"""Durable LangGraph checkpoints in Postgres (`agent` schema).

- Its own small psycopg pool, so agent traffic cannot starve the main SQLAlchemy pool.
- Strict deserialisation: graph state is plain JSON by design, so the serializer refuses
  any non-allowlisted type. A tampered checkpoint row cannot trigger code execution.
- `setup()` creates/migrates LangGraph's tables. It runs at deploy time (`manage migrate`),
  never per request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from finance_core.config import Settings
from finance_core.database.base import SCHEMA_AGENT


def _connection_kwargs(settings: Settings) -> dict[str, Any]:
    return {
        "autocommit": True,
        "row_factory": dict_row,
        # LangGraph prepares statements by default; disable behind transaction poolers.
        "prepare_threshold": 0 if settings.database_prepared_statements else None,
        # Behind a pooler, set search_path on the database role instead.
        "options": f"-c search_path={SCHEMA_AGENT}",
        "application_name": f"{settings.service_name}-agent",
    }


def strict_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=None)


@asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncIterator[AsyncPostgresSaver]:
    pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
        conninfo=settings.psycopg_conninfo,
        min_size=settings.checkpoint_pool_min_size,
        max_size=settings.checkpoint_pool_max_size,
        kwargs=_connection_kwargs(settings),
        open=False,
        name="langgraph-checkpoints",
    )
    await pool.open(wait=True, timeout=15)
    try:
        yield AsyncPostgresSaver(pool, serde=strict_serializer())
    finally:
        await pool.close()


async def setup_checkpointer(settings: Settings) -> None:
    async with open_checkpointer(settings) as saver:
        await saver.setup()
