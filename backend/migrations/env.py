"""Alembic environment (async, psycopg 3)."""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from finance_core import compat
from finance_core.config import get_settings
from finance_core.database.base import APP_SCHEMAS
from finance_core.database.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return config.attributes.get("database_url") or get_settings().sqlalchemy_url


def _include_name(name: str | None, type_: str, parent_names: object) -> bool:
    # Only manage our own schemas; LangGraph owns the `agent` schema's tables.
    if type_ == "schema":
        return name in APP_SCHEMAS
    return True


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=_include_name,
        compare_type=True,
        literal_binds=connection is None,
    )


def run_migrations_offline() -> None:
    _configure(url=_database_url())
    with context.begin_transaction():
        context.run_migrations()


def _run_sync(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(
        _database_url(),
        poolclass=pool.NullPool,
        connect_args={"prepare_threshold": None},
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run_sync)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    connection = config.attributes.get("connection")
    if connection is not None:  # called programmatically with an open connection
        _run_sync(connection)
    else:
        compat.run(_run_async())
