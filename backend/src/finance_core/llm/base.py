"""Provider-neutral LLM interface.

The rest of the application depends on these task-shaped calls, not on Gemini, LangChain,
or any SDK type. Swapping or adding a provider is a new implementation of `LLMClient`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal, Protocol

from finance_core.conversations.service import HistoryItem
from finance_core.llm.schemas import TurnUnderstanding

ReplyKind = Literal["help", "smalltalk", "out_of_scope"]


class LLMError(Exception):
    """The provider failed or returned something unusable."""


class LLMUnavailableError(LLMError):
    """No provider (including fallbacks) could serve the request."""


@dataclass(frozen=True, slots=True)
class CategoryHint:
    slug: str
    name: str
    kind: Literal["expense", "income"]


@dataclass(frozen=True, slots=True)
class PendingQuestion:
    """The question the assistant asked last, so a free-text reply can be interpreted."""

    field: str
    message: str
    options: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class UnderstandRequest:
    text: str
    today: date
    timezone: str
    base_currency: str
    locale: str
    categories: Sequence[CategoryHint]
    history: Sequence[HistoryItem] = ()
    pending: PendingQuestion | None = None


@dataclass(frozen=True, slots=True)
class UnderstandResult:
    understanding: TurnUnderstanding
    source: str  # e.g. "gemini:gemini-3.5-flash-lite" or "rules"
    latency_ms: int
    degraded: bool = False  # True when a fallback produced the result
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ReplyRequest:
    kind: ReplyKind
    text: str
    locale: str
    history: Sequence[HistoryItem] = ()


class LLMClient(Protocol):
    name: str

    async def understand(self, request: UnderstandRequest) -> UnderstandResult: ...

    def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]: ...
