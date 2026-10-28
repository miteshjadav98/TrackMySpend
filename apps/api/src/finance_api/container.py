"""Application-scoped resources, created once per process in the lifespan."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, TypeVar

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finance_core.agents.chat import ChatService
from finance_core.agents.checkpointer import open_checkpointer
from finance_core.agents.runtime import FinanceAgent
from finance_core.cache import DistributedLock, RateLimiter, RedisClient, UserDataGeneration
from finance_core.clock import Clock, SystemClock
from finance_core.config import Settings
from finance_core.database import create_engine, create_session_factory
from finance_core.email_sender import ConsoleEmailSender, EmailSender
from finance_core.llm import LLMClient, build_llm_client
from finance_core.workflows.state import AgentDeps

logger = logging.getLogger(__name__)

T = TypeVar("T")

# In-flight chat turns get this long to finish when the instance is asked to stop
# (Cloud Run sends SIGTERM and allows ~10 s by default).
_DRAIN_SECONDS = 8.0


@dataclass
class AppContainer:
    settings: Settings
    clock: Clock
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    redis: RedisClient
    generation: UserDataGeneration
    lock: DistributedLock
    rate_limiter: RateLimiter
    llm: LLMClient
    email_sender: EmailSender
    agent: FinanceAgent
    chat: ChatService
    background: set[asyncio.Task[Any]] = field(default_factory=set)

    def spawn(self, coro: Coroutine[Any, Any, T]) -> asyncio.Task[T]:
        """Run work that must outlive the HTTP request (e.g. a turn whose client left)."""
        task = asyncio.create_task(coro)
        self.background.add(task)
        task.add_done_callback(self.background.discard)
        return task

    async def drain(self) -> None:
        if not self.background:
            return
        logger.info("draining in-flight turns", extra={"count": len(self.background)})
        _, pending = await asyncio.wait(self.background, timeout=_DRAIN_SECONDS)
        for task in pending:
            task.cancel()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    clock: Clock = getattr(app.state, "clock", None) or SystemClock()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    redis = RedisClient.from_settings(settings)
    generation = UserDataGeneration(redis)
    llm: LLMClient = getattr(app.state, "llm_override", None) or build_llm_client(settings)
    email_sender: EmailSender = getattr(app.state, "email_sender", None) or ConsoleEmailSender(
        settings.environment
    )
    try:
        async with open_checkpointer(settings) as checkpointer:
            deps = AgentDeps(
                session_factory=session_factory,
                llm=llm,
                clock=clock,
                settings=settings,
                redis=redis,
                generation=generation,
            )
            agent = FinanceAgent.build(deps, checkpointer)
            lock = DistributedLock(redis)
            rate_limiter = RateLimiter(redis)
            container = AppContainer(
                settings=settings,
                clock=clock,
                engine=engine,
                session_factory=session_factory,
                redis=redis,
                generation=generation,
                lock=lock,
                rate_limiter=rate_limiter,
                llm=llm,
                email_sender=email_sender,
                agent=agent,
                chat=ChatService(deps, agent, lock=lock, rate_limiter=rate_limiter),
            )
            app.state.container = container
            logger.info(
                "api started",
                extra={"environment": settings.environment, "llmProvider": llm.name},
            )
            yield
            await container.drain()
    finally:
        await redis.close()
        await engine.dispose()
