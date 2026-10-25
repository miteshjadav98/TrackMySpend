"""One chat turn, end to end.

prepare()  -> ownership, idempotent replay, crash recovery, rate limits, per-conversation
              lock, answer validation, persist the user's message. Raises domain errors
              (404/409/422/429) *before* any streaming starts.
execute()  -> run the graph, stream events, persist the assistant's message, release
              the lock. Runs as its own task so a client disconnect cannot cut a turn
              in half.
"""

from __future__ import annotations

import asyncio
import calendar
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from langgraph.types import Command
from pydantic import TypeAdapter, ValidationError

from finance_core.agents.events import (
    InteractionEvent,
    SendMessageRequest,
    StatusEvent,
    TextDeltaEvent,
    TurnCompletedEvent,
    TurnEvent,
    TurnResult,
    TurnStartedEvent,
)
from finance_core.agents.runtime import FinanceAgent, ThreadState
from finance_core.cache.primitives import DistributedLock, LockBusyError, LockHandle, RateLimiter
from finance_core.conversations.models import Message
from finance_core.conversations.schemas import ConversationDetail
from finance_core.conversations.service import (
    ConversationService,
    conversation_view,
    message_view,
    parse_ui,
)
from finance_core.dates import parse_iso_date
from finance_core.errors import ConflictError, DomainError, ValidationFailedError
from finance_core.interactions import (
    Interaction,
    InteractionResponse,
    PendingInteraction,
    SuggestionsInteraction,
    TextInput,
)
from finance_core.money import (
    SUPPORTED_CURRENCIES,
    MoneyError,
    format_money,
    parse_amount,
    to_minor,
)
from finance_core.users.service import UserService
from finance_core.workflows.replies import DEFAULT_SUGGESTIONS
from finance_core.workflows.state import AgentDeps, TurnContext

logger = logging.getLogger(__name__)

EventSink = Callable[[TurnEvent], Awaitable[None]]
_pending_adapter: TypeAdapter[PendingInteraction] = TypeAdapter(PendingInteraction)


class TurnFailedError(DomainError):
    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message, code=code)
        self.retryable = retryable


@dataclass(slots=True)
class PreparedTurn:
    context: TurnContext
    user_message_id: uuid.UUID
    user_message: Any  # MessageView
    graph_input: dict[str, Any] | Command[Any]
    lock: LockHandle | None


def _validate_response(pending: dict[str, Any], response: InteractionResponse) -> None:
    def invalid(message: str) -> ValidationFailedError:
        return ValidationFailedError(message, code="invalid_interaction_response")

    if pending.get("type") == "confirmation":
        if response.action == "skip":
            raise invalid("This question can't be skipped.")
        return
    if response.action == "skip" and not pending.get("allowSkip"):
        raise invalid("This question can't be skipped.")
    if response.action != "submit":
        return
    values = response.value if isinstance(response.value, list) else [response.value]
    if not values or any(not isinstance(v, str) or not v.strip() for v in values):
        raise invalid("An answer is required.")
    if pending.get("inputKind") in ("single_select", "multi_select") and not pending.get(
        "allowCustomInput"
    ):
        offered = {option.get("value") for option in pending.get("options", [])}
        if any(value not in offered for value in values):
            raise invalid("Please choose one of the offered options.")


def _response_label(pending: dict[str, Any], response: InteractionResponse, locale: str) -> str:
    """Human-readable transcript text for a tapped answer."""
    if response.action == "cancel":
        return str(pending.get("cancelLabel") or "Cancel")
    if response.action == "skip":
        return "Skip"
    if pending.get("type") == "confirmation":
        return str(pending.get("confirmLabel") or "Yes")
    value = (response.first_value() or "").strip()
    for option in pending.get("options", []):
        if option.get("value") == value:
            return str(option.get("label") or value)
    if pending.get("inputKind") == "date" and (day := parse_iso_date(value)):
        return f"{day.day} {calendar.month_abbr[day.month]} {day.year}"
    currency = pending.get("currency")
    if pending.get("inputKind") == "amount" and currency in SUPPORTED_CURRENCIES:
        amount = parse_amount(value)
        if amount is not None:
            try:
                return format_money(to_minor(amount, currency), currency, locale)
            except MoneyError:
                pass
    return value[:200]


class ChatService:
    def __init__(
        self,
        deps: AgentDeps,
        agent: FinanceAgent,
        *,
        lock: DistributedLock | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._deps = deps
        self._agent = agent
        self._lock = lock
        self._rate_limiter = rate_limiter

    # -- reads ----------------------------------------------------------------------------

    async def _pending_model(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID
    ) -> PendingInteraction | None:
        raw = await self._agent.pending(user_id, conversation_id)
        if raw is None:
            return None
        try:
            return _pending_adapter.validate_python(raw)
        except ValidationError:
            logger.warning("unreadable pending interaction; ignoring")
            return None

    async def detail(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, *, limit: int = 50
    ) -> ConversationDetail:
        async with self._deps.session_factory() as session:
            conversations = ConversationService(session, clock=self._deps.clock)
            row = await conversations.get_owned(user_id, conversation_id)
            page = await conversations.messages(user_id, conversation_id, limit=limit)
        return ConversationDetail(
            conversation=conversation_view(row),
            messages=page.items,
            has_more_messages=page.has_more,
            pending_interaction=await self._pending_model(user_id, conversation_id),
            suggestions=list(DEFAULT_SUGGESTIONS) if not page.items else [],
        )

    async def delete_conversation(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        async with self._deps.session_factory() as session:
            await ConversationService(session, clock=self._deps.clock).delete(
                user_id, conversation_id
            )
        await self._agent.delete_thread(user_id, conversation_id)

    # -- turn lifecycle -------------------------------------------------------------------

    async def prepare(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        request: SendMessageRequest,
        *,
        request_id: str | None = None,
    ) -> PreparedTurn | TurnResult:
        settings = self._deps.settings
        async with self._deps.session_factory() as session:
            conversations = ConversationService(session, clock=self._deps.clock)
            await conversations.get_owned(user_id, conversation_id)
            user_ctx = await UserService(session).context(user_id)
            existing = await conversations.find_user_message(
                conversation_id, request.client_message_id
            )
            if existing is not None:
                reply = await conversations.reply_to(existing.id)
                if reply is not None:  # a retry of a finished turn: replay, don't re-run
                    return TurnResult(
                        user_message=message_view(existing),
                        assistant_message=message_view(reply),
                        pending_interaction=await self._pending_model(user_id, conversation_id),
                        replayed=True,
                    )

        if existing is None:
            await self._enforce_rate_limits(user_id)
        lock = await self._acquire_lock(conversation_id)
        try:
            state = await self._agent.thread_state(user_id, conversation_id)
            if existing is not None and state.last_message_id == str(existing.id):
                # The graph finished this message but the reply was never written (crash in
                # between). Rebuild the reply from the checkpoint instead of re-running.
                return await self._recover(user_id, conversation_id, existing, state)

            text, content, meta, resume = self._interpret(request, state.pending, user_ctx.locale)
            async with self._deps.session_factory() as session:
                conversations = ConversationService(session, clock=self._deps.clock)
                row, _ = await conversations.add_user_message(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    client_message_id=request.client_message_id,
                    content=content,
                    meta=meta,
                )
                history = await conversations.history_window(
                    conversation_id, limit=settings.agent_history_window, exclude_id=row.id
                )
                user_view = message_view(row)

            graph_input: dict[str, Any] | Command[Any]
            if state.pending is not None:
                graph_input = Command(resume={**resume, "messageId": str(row.id)})
            else:
                graph_input = {
                    "user_text": text,
                    "message_id": str(row.id),
                    "history": [{"role": h.role, "text": h.text} for h in history],
                }
            context = TurnContext(
                user_id=user_id,
                conversation_id=conversation_id,
                base_currency=user_ctx.base_currency,
                timezone=user_ctx.timezone,
                locale=user_ctx.locale,
                today=user_ctx.today(self._deps.clock),
                request_id=request_id,
            )
            prepared = PreparedTurn(
                context=context,
                user_message_id=row.id,
                user_message=user_view,
                graph_input=graph_input,
                lock=lock,
            )
            lock = None  # ownership passes to execute()
            return prepared
        finally:
            if lock is not None:
                await self._release(lock)

    async def execute(self, turn: PreparedTurn, emit: EventSink) -> TurnResult:
        settings = self._deps.settings
        try:
            await emit(TurnStartedEvent(user_message=turn.user_message))

            async def on_event(event: dict[str, Any]) -> None:
                if event.get("type") == "status":
                    await emit(
                        StatusEvent(stage=str(event.get("stage")), label=str(event.get("label")))
                    )
                elif event.get("type") == "text.delta" and event.get("delta"):
                    await emit(TextDeltaEvent(delta=str(event["delta"])))

            try:
                outcome = await asyncio.wait_for(
                    self._agent.run(turn.context, turn.graph_input, on_event),
                    timeout=settings.agent_turn_timeout_seconds,
                )
            except TimeoutError:
                raise TurnFailedError(
                    "That took longer than expected. Please try again.",
                    code="turn_timeout",
                    retryable=True,
                ) from None

            content, ui, pending = self._assistant_payload(outcome.pending, outcome.reply)
            meta = {
                "intent": outcome.intent,
                "source": outcome.source,
                "outcome": outcome.outcome,
                "degraded": outcome.degraded,
            }
            assistant = await self._save_assistant(
                turn.context, turn.user_message_id, content, ui, meta
            )
            for item in ui:
                if not isinstance(item, SuggestionsInteraction):
                    await emit(InteractionEvent(interaction=item))
            result = TurnResult(
                user_message=turn.user_message,
                assistant_message=assistant,
                pending_interaction=pending,
            )
            await emit(TurnCompletedEvent(result=result))
            logger.info(
                "turn completed",
                extra={
                    "intent": outcome.intent,
                    "outcome": outcome.outcome,
                    "llmSource": outcome.source,
                },
            )
            return result
        finally:
            await self._release(turn.lock)

    # -- helpers --------------------------------------------------------------------------

    def _interpret(
        self, request: SendMessageRequest, pending: dict[str, Any] | None, locale: str
    ) -> tuple[str, str, dict[str, Any] | None, dict[str, Any]]:
        """Returns (text for the model, transcript content, message meta, resume payload)."""
        turn_input = request.input
        if isinstance(turn_input, TextInput):
            text = turn_input.text.strip()[: self._deps.settings.agent_max_input_chars]
            if not text:
                raise ValidationFailedError("Message can't be empty.", details={"field": "text"})
            return text, text, None, ({"kind": "text", "text": text} if pending else {})

        assert isinstance(turn_input, InteractionResponse)
        if pending is None or pending.get("id") != turn_input.interaction_id:
            raise ValidationFailedError(
                "That question is no longer waiting for an answer.", code="interaction_expired"
            )
        _validate_response(pending, turn_input)
        label = _response_label(pending, turn_input, locale)
        payload = turn_input.model_dump(mode="json", by_alias=True)
        resume = {
            "kind": "response",
            "interactionId": turn_input.interaction_id,
            "action": turn_input.action,
            "value": payload.get("value"),
        }
        return label, label, {"interactionResponse": payload}, resume

    def _assistant_payload(
        self, pending: dict[str, Any] | None, reply: dict[str, Any] | None
    ) -> tuple[str, list[Interaction], PendingInteraction | None]:
        if pending is not None:
            model = _pending_adapter.validate_python(pending)
            return model.message, [model], model
        reply = reply or {}
        return str(reply.get("text") or "Done."), parse_ui(reply.get("ui")), None

    async def _save_assistant(
        self,
        context: TurnContext,
        reply_to_id: uuid.UUID,
        content: str,
        ui: list[Interaction],
        meta: dict[str, Any],
    ) -> Any:
        async with self._deps.session_factory() as session:
            row = await ConversationService(session, clock=self._deps.clock).add_assistant_message(
                user_id=context.user_id,
                conversation_id=context.conversation_id,
                reply_to_id=reply_to_id,
                content=content,
                ui=ui,
                meta=meta,
            )
            return message_view(row)

    async def _recover(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        user_message: Message,
        state: ThreadState,
    ) -> TurnResult:
        content, ui, pending = self._assistant_payload(state.pending, state.reply)
        async with self._deps.session_factory() as session:
            conversations = ConversationService(session, clock=self._deps.clock)
            row = await conversations.add_assistant_message(
                user_id=user_id,
                conversation_id=conversation_id,
                reply_to_id=user_message.id,
                content=content,
                ui=ui,
                meta={"recovered": True},
            )
        logger.warning("recovered a turn whose reply was not persisted")
        return TurnResult(
            user_message=message_view(user_message),
            assistant_message=message_view(row),
            pending_interaction=pending,
            replayed=True,
        )

    async def _enforce_rate_limits(self, user_id: uuid.UUID) -> None:
        if self._rate_limiter is None:
            return
        settings = self._deps.settings
        await self._rate_limiter.hit(
            "chat-minute",
            str(user_id),
            limit=settings.rate_limit_chat_per_minute,
            window_seconds=60,
        )
        await self._rate_limiter.hit(
            "chat-day", str(user_id), limit=settings.rate_limit_chat_per_day, window_seconds=86_400
        )

    async def _acquire_lock(self, conversation_id: uuid.UUID) -> LockHandle | None:
        if self._lock is None:
            return None
        try:
            return await self._lock.acquire(
                f"conversation:{conversation_id}",
                ttl_seconds=self._deps.settings.agent_turn_timeout_seconds + 15,
            )
        except LockBusyError:
            raise ConflictError(
                "I'm still working on your previous message.", code="conversation_busy"
            ) from None

    async def _release(self, lock: LockHandle | None) -> None:
        if lock is not None and self._lock is not None:
            await self._lock.release(lock)
