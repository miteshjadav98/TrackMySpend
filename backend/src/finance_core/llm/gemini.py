"""Gemini on Vertex AI, via LangChain's ChatGoogleGenerativeAI (google-genai SDK).

Authentication uses Application Default Credentials: `gcloud auth application-default
login` locally, the Cloud Run service account in deployment. No API keys.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from finance_core.config import Settings
from finance_core.conversations.service import HistoryItem
from finance_core.llm import prompts
from finance_core.llm.base import LLMError, ReplyRequest, UnderstandRequest, UnderstandResult
from finance_core.llm.schemas import TurnUnderstanding

logger = logging.getLogger(__name__)


def _history_messages(history: Sequence[HistoryItem]) -> list[BaseMessage]:
    """Chat history as alternating turns, starting with the user (as Gemini expects)."""
    messages: list[BaseMessage] = []
    for item in history:
        if not messages and item.role != "user":
            continue
        message_cls = HumanMessage if item.role == "user" else AIMessage
        if messages and isinstance(messages[-1], message_cls):
            previous = messages[-1]
            messages[-1] = message_cls(content=f"{previous.content}\n{item.text}")
        else:
            messages.append(message_cls(content=item.text))
    if messages and isinstance(messages[-1], HumanMessage):
        # The current message is appended next; avoid two user turns in a row.
        messages.append(AIMessage(content="(noted)"))
    return messages


def render_understand_prompt(request: UnderstandRequest) -> str:
    expense = ", ".join(f"{c.slug}: {c.name}" for c in request.categories if c.kind == "expense")
    income = ", ".join(f"{c.slug}: {c.name}" for c in request.categories if c.kind == "income")
    pending_block = ""
    if request.pending is not None:
        options = ", ".join(request.pending.options)
        pending_block = prompts.load("pending_block_v1").format(
            question="(see the assistant's last message)",
            field=request.pending.field,
            options_line=f"Options offered: {options}." if options else "",
        )
    return prompts.load("understand_v1").format(
        today_long=request.today.strftime("%A, %d %B %Y"),
        today_iso=request.today.isoformat(),
        timezone=request.timezone,
        base_currency=request.base_currency,
        expense_categories=expense or "(none)",
        income_categories=income or "(none)",
        pending_block=pending_block,
    )


def _usage(message: Any) -> dict[str, Any]:
    usage = getattr(message, "usage_metadata", None) or {}
    return {
        k: usage.get(k) for k in ("input_tokens", "output_tokens", "total_tokens") if k in usage
    }


class GeminiLLMClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.gcp_project:
            raise ValueError("GCP_PROJECT must be set to use the gemini LLM provider")
        common: dict[str, Any] = {
            "vertexai": True,
            "project": settings.gcp_project,
            "location": settings.vertex_location,
            "timeout": settings.llm_timeout_seconds,
            "max_retries": settings.llm_max_retries,
        }
        # Gemini 3.x models use fixed sampling defaults, so no temperature is passed.
        self._understand_model = settings.llm_understand_model
        self._reply_model = settings.llm_reply_model
        self.name = f"gemini:{self._understand_model}"
        understand_model = ChatGoogleGenerativeAI(
            model=self._understand_model,
            thinking_level=settings.llm_understand_thinking,
            labels={"app": "moneymoney", "task": "understand"},
            **common,
        )
        self._understander = understand_model.with_structured_output(
            TurnUnderstanding, method="json_schema", include_raw=True
        )
        self._replier = ChatGoogleGenerativeAI(
            model=self._reply_model,
            thinking_level=settings.llm_reply_thinking,
            max_output_tokens=400,
            labels={"app": "moneymoney", "task": "reply"},
            **common,
        )

    async def understand(self, request: UnderstandRequest) -> UnderstandResult:
        messages: list[BaseMessage] = [
            SystemMessage(content=render_understand_prompt(request)),
            *_history_messages(request.history),
            HumanMessage(content=request.text),
        ]
        started = time.perf_counter()
        result = await self._understander.ainvoke(messages)
        latency_ms = int((time.perf_counter() - started) * 1000)
        if not isinstance(result, dict):  # include_raw=True always returns a dict
            raise LLMError("Unexpected structured-output shape")
        parsed = result.get("parsed")
        if not isinstance(parsed, TurnUnderstanding):
            error = result.get("parsing_error")
            raise LLMError(f"Gemini returned unparseable output: {type(error).__name__}")
        usage = _usage(result.get("raw"))
        logger.info(
            "llm understand",
            extra={
                "llmModel": self._understand_model,
                "promptVersion": prompts.UNDERSTAND_PROMPT_VERSION,
                "latencyMs": latency_ms,
                "intent": parsed.intent,
                "transactionCount": len(parsed.transactions),
                **{f"usage_{k}": v for k, v in usage.items()},
            },
        )
        return UnderstandResult(
            understanding=parsed, source=self.name, latency_ms=latency_ms, usage=usage
        )

    async def stream_reply(self, request: ReplyRequest) -> AsyncIterator[str]:
        messages: list[BaseMessage] = [
            SystemMessage(content=prompts.load("reply_v1").format(kind=request.kind)),
            *_history_messages(request.history),
            HumanMessage(content=request.text),
        ]
        started = time.perf_counter()
        async for chunk in self._replier.astream(messages):
            text = chunk.text
            if text:
                yield text
        logger.info(
            "llm reply",
            extra={
                "llmModel": self._reply_model,
                "promptVersion": prompts.REPLY_PROMPT_VERSION,
                "latencyMs": int((time.perf_counter() - started) * 1000),
                "replyKind": request.kind,
            },
        )
