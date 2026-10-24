"""Checkpoint retention.

Checkpoints are working memory, not records: the transcript lives in `chat.messages` and
financial data in the ledger. So old checkpoints are safe to drop:
- threads of conversations idle longer than N days are deleted (any pending question
  expired long ago; the next message simply starts a fresh run);
- threads whose conversation no longer exists are deleted;
- active threads keep only their latest checkpoint.

Run on a schedule (Cloud Scheduler -> Cloud Run job): `python -m finance_core.manage prune-checkpoints`.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, text

from finance_core.agents.checkpointer import open_checkpointer
from finance_core.agents.runtime import thread_id
from finance_core.config import Settings
from finance_core.conversations.models import Conversation
from finance_core.database.engine import create_engine, create_session_factory

logger = logging.getLogger(__name__)

_BATCH = 200

_ORPHANS_SQL = text(
    """
    SELECT DISTINCT c.thread_id
    FROM agent.checkpoints AS c
    WHERE NOT EXISTS (
        SELECT 1 FROM chat.conversations AS v
        WHERE c.thread_id = 'user:' || v.user_id::text || ':conversation:' || v.id::text
    )
    LIMIT 2000
    """
)


async def prune_checkpoints(settings: Settings, *, inactive_days: int = 30) -> dict[str, int]:
    cutoff = datetime.now(UTC) - timedelta(days=inactive_days)
    engine = create_engine(settings)
    try:
        async with create_session_factory(engine)() as session:
            rows = (
                await session.execute(select(Conversation.user_id, Conversation.id, Conversation.last_message_at))
            ).all()
            orphans = [row[0] for row in (await session.execute(_ORPHANS_SQL)).all()]
    finally:
        await engine.dispose()

    idle = [thread_id(u, c) for u, c, last in rows if last < cutoff]
    active = [thread_id(u, c) for u, c, last in rows if last >= cutoff]
    async with open_checkpointer(settings) as saver:
        for start in range(0, len(idle), _BATCH):
            await saver.aprune(idle[start : start + _BATCH], strategy="delete")
        for start in range(0, len(active), _BATCH):
            await saver.aprune(active[start : start + _BATCH], strategy="keep_latest")
        for orphan in orphans:
            await saver.adelete_thread(orphan)
    stats = {"idleDeleted": len(idle), "activePruned": len(active), "orphansDeleted": len(orphans)}
    logger.info("checkpoint retention complete", extra=stats)
    return stats
