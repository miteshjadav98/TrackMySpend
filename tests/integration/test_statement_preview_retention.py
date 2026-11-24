"""Statement previews are deleted after expiry even when their owners stay away."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_api import container as api_container
from finance_api.main import create_app
from finance_core.audit.models import AuditEvent
from finance_core.clock import Clock, FixedClock
from finance_core.config import Settings
from finance_core.imports.maintenance import prune_import_previews
from finance_core.imports.models import ImportRow, StatementImport
from tests.conftest import NOW, register
from tests.integration.test_statement_imports import import_statement, make_account, upload


async def test_the_retention_task_retries_and_deletes_expired_previews_across_users(
    client: httpx.AsyncClient,
    make_client: Any,
    app: Any,
    settings: Settings,
    clock: FixedClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await register(client)
    account_id = await make_account(client)
    saved = await import_statement(client, account_id)
    first_expired = await upload(client, account_id)
    second_owner = make_client()
    await register(second_owner)
    second_expired = await upload(second_owner, await make_account(second_owner))
    expired_ids = {uuid.UUID(detail["id"]) for detail in (first_expired, second_expired)}

    clock.set(NOW + timedelta(hours=25))
    try:
        active_owner = make_client()
        await register(active_owner)
        active = await upload(active_owner, await make_account(active_owner))
        preserved_ids = {uuid.UUID(detail["id"]) for detail in (saved, active)}
        swept = asyncio.Event()
        attempts = 0

        async def fail_once_then_prune(
            session_factory: async_sessionmaker[AsyncSession], *, clock: Clock
        ) -> int:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise OperationalError(None, None, RuntimeError("temporary database outage"))
            count = await prune_import_previews(session_factory, clock=clock)
            swept.set()
            return count

        monkeypatch.setattr(api_container, "prune_import_previews", fail_once_then_prune)
        monkeypatch.setattr(api_container, "_IMPORT_RETENTION_INTERVAL_SECONDS", 0.01)
        restarted = create_app(settings, clock=clock)
        async with restarted.router.lifespan_context(restarted):
            await asyncio.wait_for(swept.wait(), timeout=5)

        async with app.state.container.session_factory() as session:
            remaining = await session.scalars(
                select(StatementImport.id).where(
                    StatementImport.id.in_(expired_ids | preserved_ids)
                )
            )
            assert set(remaining) == preserved_ids
            expired_rows = await session.scalars(
                select(ImportRow.id).where(ImportRow.import_id.in_(expired_ids))
            )
            assert list(expired_rows) == []
            audited = await session.scalars(
                select(AuditEvent.entity_id).where(
                    AuditEvent.entity_id.in_(expired_ids), AuditEvent.action == "import.expired"
                )
            )
            assert sorted(audited) == sorted(expired_ids)
        assert attempts >= 2
    finally:
        clock.set(NOW)
