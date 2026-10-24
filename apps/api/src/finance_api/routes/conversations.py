from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterable
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.sse import EventSourceResponse, ServerSentEvent

from finance_api.container import AppContainer
from finance_api.deps import ContainerDep, PrincipalDep, RequestIdDep, SessionDep
from finance_core.agents.chat import PreparedTurn, TurnFailedError
from finance_core.agents.events import (
    SendMessageRequest,
    TurnCompletedEvent,
    TurnErrorEvent,
    TurnEvent,
    TurnResult,
)
from finance_core.conversations.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationPage,
    ConversationUpdate,
    ConversationView,
    MessagePage,
)
from finance_core.conversations.service import ConversationService
from finance_core.errors import DomainError
from finance_core.observability import conversation_id_var, request_id_var

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    principal: PrincipalDep,
    session: SessionDep,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    include_archived: Annotated[bool, Query(alias="includeArchived")] = False,
) -> ConversationPage:
    return await ConversationService(session, clock=container.clock).list_conversations(
        principal.user_id, limit=limit, cursor=cursor, include_archived=include_archived
    )


@router.post("", status_code=201)
async def create_conversation(
    body: ConversationCreate, principal: PrincipalDep, session: SessionDep, container: ContainerDep
) -> ConversationView:
    return await ConversationService(session, clock=container.clock).create(
        principal.user_id, body.title
    )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    principal: PrincipalDep,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ConversationDetail:
    """Transcript plus any question the assistant is still waiting on (resume after refresh)."""
    return await container.chat.detail(principal.user_id, conversation_id, limit=limit)


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    container: ContainerDep,
    before: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> MessagePage:
    return await ConversationService(session, clock=container.clock).messages(
        principal.user_id, conversation_id, limit=limit, before=before
    )


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: uuid.UUID,
    body: ConversationUpdate,
    principal: PrincipalDep,
    session: SessionDep,
    container: ContainerDep,
) -> ConversationView:
    return await ConversationService(session, clock=container.clock).update(
        principal.user_id, conversation_id, body
    )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: uuid.UUID, principal: PrincipalDep, container: ContainerDep
) -> None:
    await container.chat.delete_conversation(principal.user_id, conversation_id)


# -- chat turns ---------------------------------------------------------------------------


async def prepare_turn(
    conversation_id: uuid.UUID,
    body: SendMessageRequest,
    principal: PrincipalDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> PreparedTurn | TurnResult:
    """Runs before any response bytes are sent, so failures are real HTTP errors."""
    conversation_id_var.set(str(conversation_id))
    return await container.chat.prepare(
        principal.user_id, conversation_id, body, request_id=request_id
    )


PreparedTurnDep = Annotated[PreparedTurn | TurnResult, Depends(prepare_turn)]


def _error_event(exc: BaseException) -> TurnErrorEvent:
    if isinstance(exc, DomainError):
        return TurnErrorEvent(
            code=exc.code,
            message=exc.message,
            retryable=bool(getattr(exc, "retryable", False)),
            request_id=request_id_var.get(),
        )
    return TurnErrorEvent(
        code="internal_error",
        message="Something went wrong. Please try again.",
        retryable=True,
        request_id=request_id_var.get(),
    )


async def _run_turn(
    container: AppContainer, prepared: PreparedTurn, queue: asyncio.Queue[TurnEvent | None]
) -> None:
    try:
        await container.chat.execute(prepared, queue.put)
    except Exception as exc:
        if not isinstance(exc, TurnFailedError):
            logger.exception("chat turn failed")
        await queue.put(_error_event(exc))
    finally:
        await queue.put(None)


def _sse(event: TurnEvent) -> ServerSentEvent:
    return ServerSentEvent(event=event.type, raw_data=event.model_dump_json(by_alias=True))


@router.post(
    "/{conversation_id}/messages/stream",
    response_class=EventSourceResponse,
    responses={
        200: {
            "description": "Server-sent events. Each event's `data` is a JSON `TurnEvent`; "
            "the stream ends after `turn.completed` or `error`."
        }
    },
)
async def stream_message(
    prepared: PreparedTurnDep, container: ContainerDep
) -> AsyncIterable[ServerSentEvent]:
    if isinstance(prepared, TurnResult):  # idempotent replay of a finished turn
        yield _sse(TurnCompletedEvent(result=prepared))
        return
    queue: asyncio.Queue[TurnEvent | None] = asyncio.Queue()
    # The turn runs in its own task: if the client disconnects, the stream stops but the
    # turn still completes and persists, and the reply is there on reload.
    container.spawn(_run_turn(container, prepared, queue))
    while (event := await queue.get()) is not None:
        yield _sse(event)


@router.post("/{conversation_id}/messages")
async def send_message(prepared: PreparedTurnDep, container: ContainerDep) -> TurnResult:
    """Non-streaming variant for server-to-server callers (MCP tools, integrations)."""
    if isinstance(prepared, TurnResult):
        return prepared

    async def discard(_: TurnEvent) -> None:
        return None

    task = container.spawn(container.chat.execute(prepared, discard))
    return await asyncio.shield(task)
