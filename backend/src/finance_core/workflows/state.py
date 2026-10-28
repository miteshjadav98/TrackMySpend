"""Graph state, input schema, runtime context, and dependencies.

State rules (see docs/architecture.md):
- Plain JSON values only (dicts, lists, strings, numbers): checkpoints stay small,
  deserialisation can run in strict mode, and schema evolution is just "read with defaults".
- Every key has exactly one writer per step, so no reducers are needed.
- Identity (user, conversation) lives in `TurnContext`, never in state: a node cannot
  change who it is acting for, and identity is not copied into every checkpoint.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finance_core.cache.primitives import UserDataGeneration
from finance_core.cache.redis import RedisClient
from finance_core.clock import Clock
from finance_core.config import Settings
from finance_core.llm.base import LLMClient
from finance_core.users.context import UserContext


class HistoryEntry(TypedDict):
    role: Literal["user", "assistant"]
    text: str


class GraphInput(TypedDict):
    """What a new turn supplies. Everything else is derived or carried in the checkpoint."""

    user_text: str
    message_id: str
    history: list[HistoryEntry]


class FinanceState(TypedDict, total=False):
    # turn input
    user_text: str
    message_id: str
    history: list[HistoryEntry]
    # The chat message this checkpoint last processed. Lets the chat layer recover a turn
    # whose graph run finished but whose transcript write was lost (crash in between).
    last_message_id: str | None
    # understanding
    intent: str
    source: str
    degraded: bool
    followup: dict[str, Any] | None  # the question a free-text reply may be answering
    abandoned: bool  # the user moved on from an unfinished entry
    # transaction workflow
    drafts: list[dict[str, Any]]
    pending: dict[str, Any] | None  # interaction payload the user must answer
    rounds: int  # clarification rounds so far (bounded)
    notice: str | None  # e.g. "That doesn't look like an amount."
    # insights / search
    period: dict[str, Any] | None
    search: dict[str, Any] | None
    # results
    outcome: str | None
    saved: list[dict[str, Any]]
    filed_by_merchant_rule: list[str]  # ids of saved transactions a merchant rule filed
    summary: dict[str, Any] | None
    results: dict[str, Any] | None
    reply: dict[str, Any] | None  # {"text": str, "ui": [interaction, ...]}


@dataclass(frozen=True, slots=True)
class TurnContext:
    """Immutable per-run context (LangGraph `context_schema`). Not checkpointed."""

    user_id: uuid.UUID
    conversation_id: uuid.UUID
    base_currency: str
    timezone: str
    locale: str
    today: date
    request_id: str | None = None

    @property
    def user(self) -> UserContext:
        return UserContext(
            user_id=self.user_id,
            base_currency=self.base_currency,
            timezone=self.timezone,
            locale=self.locale,
        )


@dataclass(frozen=True, slots=True)
class AgentDeps:
    """Application-scoped services the graph's nodes use (built once at startup)."""

    session_factory: async_sessionmaker[AsyncSession]
    llm: LLMClient
    clock: Clock
    settings: Settings
    redis: RedisClient | None = None
    generation: UserDataGeneration | None = None


def status_event(stage: str, label: str) -> dict[str, str]:
    return {"type": "status", "stage": stage, "label": label}


def text_event(delta: str) -> dict[str, str]:
    return {"type": "text.delta", "delta": delta}
