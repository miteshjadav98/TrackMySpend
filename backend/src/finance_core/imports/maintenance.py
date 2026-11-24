"""Retention for expired statement previews, independent of the owner's activity."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_core.clock import Clock
from finance_core.imports.service import ImportService


async def prune_import_previews(
    session_factory: async_sessionmaker[AsyncSession], *, clock: Clock
) -> int:
    """Delete expired previews across all users and audit the deletions."""
    async with session_factory() as session:
        return await ImportService(session, clock=clock).purge_expired()
