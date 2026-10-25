"""Timeouts and provider failover around any `LLMClient`.

Degradation policy (decided up front, not by whichever exception escapes first):
- understanding: primary model -> deterministic rules engine -> LLMUnavailableError
- replies:       primary model -> canned rules reply (only if nothing was streamed yet)
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import cast

from finance_core.llm.base import (
    LLMClient,
    LLMUnavailableError,
    ReplyRequest,
    UnderstandRequest,
    UnderstandResult,
)

logger = logging.getLogger(__name__)


class ResilientLLMClient:
    def __init__(
        self, primary: LLMClient, fallback: LLMClient | None, *, timeout_seconds: float
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._timeout = timeout_seconds
        self.name = primary.name

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        try:
            return await asyncio.wait_for(self._primary.understand(request), self._timeout)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # provider SDK errors vary; all mean "use the fallback"
            logger.warning(
                "llm understand failed; degrading",
                extra={"llmProvider": self._primary.name, "errorType": type(exc).__name__},
            )
            if self._fallback is None:
                raise LLMUnavailableError("The language model is unavailable") from exc
            result = await self._fallback.understand(request)
            return dataclasses.replace(result, degraded=True)

    async def _bounded(self, source: AsyncIterator[str]) -> AsyncGenerator[str]:
        """Enforce a total time budget without wrapping `yield` in a cancel scope."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._timeout
        stream = cast(AsyncGenerator[str], source)  # every client implements replies as generators
        async with aclosing(stream):
            iterator = aiter(stream)
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise TimeoutError("reply stream exceeded its time budget")
                try:
                    chunk = await asyncio.wait_for(anext(iterator), remaining)
                except StopAsyncIteration:
                    return
                yield chunk

    async def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]:
        produced = False
        fallback: LLMClient | None = None
        try:
            async with aclosing(self._bounded(self._primary.stream_reply(request))) as stream:
                async for chunk in stream:
                    produced = True
                    yield chunk
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "llm reply failed",
                extra={"llmProvider": self._primary.name, "errorType": type(exc).__name__},
            )
            if not produced:  # if text was already streamed, keep it and stop there
                fallback = self._fallback
        if fallback is not None:
            async for chunk in fallback.stream_reply(request):
                yield chunk
