"""Async SQLAlchemy engine and session factory (psycopg 3 driver)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from finance_core.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    connect_args: dict[str, Any] = {"application_name": settings.service_name}
    if settings.database_statement_timeout_ms > 0:
        # A runaway query must not hold a pooled connection. Behind a transaction-mode
        # pooler, set this on the database role instead and configure 0 here.
        connect_args["options"] = (
            f"-c statement_timeout={settings.database_statement_timeout_ms} "
            "-c idle_in_transaction_session_timeout=30000"
        )
    if not settings.database_prepared_statements:
        connect_args["prepare_threshold"] = None
    return create_async_engine(
        settings.sqlalchemy_url,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_timeout=settings.database_pool_timeout_seconds,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args=connect_args,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
