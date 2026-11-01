"""Settlements over HTTP: recording, listing and deleting money paid between friends."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from finance_api.deps import ContainerDep, RequestIdDep, SessionDep, UserContextDep
from finance_core.friends.schemas import (
    SettlementAccountTag,
    SettlementCreate,
    SettlementCreated,
    SettlementView,
)
from finance_core.friends.settlements import SettlementService

router = APIRouter(prefix="/api/v1/settlements", tags=["settlements"])

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        pattern=r"^[A-Za-z0-9._:-]{8,100}$",
        description="Client-generated key; repeating it returns the original settlement.",
    ),
]


def _service(session: SessionDep, container: ContainerDep) -> SettlementService:
    return SettlementService(session, clock=container.clock)


@router.get("")
async def list_settlements(
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    friend_id: Annotated[uuid.UUID | None, Query(alias="friendId")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[SettlementView]:
    return await _service(session, container).list_settlements(
        ctx, friend_id=friend_id, limit=limit
    )


@router.post(
    "",
    status_code=201,
    responses={200: {"model": SettlementCreated, "description": "Idempotent replay"}},
)
async def create_settlement(
    body: SettlementCreate,
    response: Response,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
    idempotency_key: IdempotencyKey = None,
) -> SettlementCreated:
    created, is_new = await _service(session, container).create(
        ctx,
        body,
        # Namespaced so client keys can never collide with keys the agent generates.
        idempotency_key=f"api:{idempotency_key}" if idempotency_key else None,
        request_id=request_id,
    )
    if not is_new:
        response.status_code = 200
    return created


@router.patch("/{settlement_id}")
async def tag_settlement_account(
    settlement_id: uuid.UUID,
    body: SettlementAccountTag,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> SettlementView:
    """A linked friend's own account on a settlement the other person recorded."""
    return await _service(session, container).tag_account(
        ctx, settlement_id, body, request_id=request_id
    )


@router.delete("/{settlement_id}", status_code=204)
async def delete_settlement(
    settlement_id: uuid.UUID,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> Response:
    await _service(session, container).delete(ctx, settlement_id, request_id=request_id)
    return Response(status_code=204)
