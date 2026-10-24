"""FinanceAgent: owns the compiled graph and its checkpointer; one call per chat turn."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command

from finance_core.config import Settings
from finance_core.workflows.graph import GRAPH_VERSION, build_graph
from finance_core.workflows.state import AgentDeps, TurnContext

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class AgentOutcome:
    pending: dict[str, Any] | None  # the question the run paused on, if any
    reply: dict[str, Any] | None  # {"text", "ui"} when the run completed
    intent: str | None
    source: str | None
    outcome: str | None
    degraded: bool


@dataclass(frozen=True, slots=True)
class ThreadState:
    pending: dict[str, Any] | None
    reply: dict[str, Any] | None
    last_message_id: str | None


def thread_id(user_id: uuid.UUID, conversation_id: uuid.UUID) -> str:
    # Both ids are unguessable, and ownership is checked before any thread access; the
    # user prefix is defence in depth against a conversation id ever crossing users.
    return f"user:{user_id}:conversation:{conversation_id}"


class FinanceAgent:
    def __init__(
        self,
        graph: CompiledStateGraph[Any, Any, Any, Any],
        checkpointer: BaseCheckpointSaver[Any],
        settings: Settings,
    ) -> None:
        self._graph = graph
        self._checkpointer = checkpointer
        self._settings = settings

    @classmethod
    def build(
        cls, deps: AgentDeps, checkpointer: BaseCheckpointSaver[Any]
    ) -> FinanceAgent:
        graph = build_graph(deps).compile(checkpointer=checkpointer, name="finance-agent")
        return cls(graph, checkpointer, deps.settings)

    def _config(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, request_id: str | None = None
    ) -> RunnableConfig:
        return {
            "configurable": {"thread_id": thread_id(user_id, conversation_id)},
            "recursion_limit": self._settings.agent_recursion_limit,
            "metadata": {"graph_version": GRAPH_VERSION, "request_id": request_id},
            "tags": ["moneymoney", GRAPH_VERSION],
        }

    async def thread_state(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> ThreadState:
        snapshot = await self._graph.aget_state(self._config(user_id, conversation_id))
        values = snapshot.values or {}
        pending: dict[str, Any] | None = None
        if snapshot.interrupts:
            value = snapshot.interrupts[0].value
            if isinstance(value, dict) and not self._expired(snapshot.created_at):
                pending = value
        return ThreadState(
            pending=pending,
            reply=None if snapshot.interrupts else values.get("reply"),
            last_message_id=values.get("last_message_id"),
        )

    async def pending(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> dict[str, Any] | None:
        return (await self.thread_state(user_id, conversation_id)).pending

    def _expired(self, created_at: str | None) -> bool:
        """An unanswered question goes stale; the next message then starts fresh."""
        if not created_at:
            return False
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError:
            return False
        age = datetime.now(created.tzinfo) - created
        return age > timedelta(hours=self._settings.agent_pending_ttl_hours)

    async def run(
        self,
        context: TurnContext,
        graph_input: dict[str, Any] | Command[Any],
        on_event: EventCallback,
    ) -> AgentOutcome:
        config = self._config(context.user_id, context.conversation_id, context.request_id)
        async for mode, chunk in self._graph.astream(
            graph_input,  # type: ignore[arg-type]
            config,
            context=context,
            stream_mode=["custom", "updates"],
            durability=self._settings.agent_checkpoint_durability,
        ):
            if mode == "custom" and isinstance(chunk, dict):
                await on_event(chunk)
        snapshot = await self._graph.aget_state(config)
        values = snapshot.values or {}
        pending = snapshot.interrupts[0].value if snapshot.interrupts else None
        return AgentOutcome(
            pending=pending if isinstance(pending, dict) else None,
            reply=None if pending else values.get("reply"),
            intent=values.get("intent"),
            source=values.get("source"),
            outcome=values.get("outcome"),
            degraded=bool(values.get("degraded")),
        )

    async def delete_thread(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        await self._checkpointer.adelete_thread(thread_id(user_id, conversation_id))
