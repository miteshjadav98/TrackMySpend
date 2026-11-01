"""Settlements over HTTP: recording, listing and deleting money paid between friends."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Response

from finance_api.deps import ContainerDep, RequestIdDep, SessionDep, UserContextDep
from finance_core.friends.schemas import SettlementCreate, SettlementCreated, SettlementView
from finance_core.friends.settlements import SettlementService

router = APIRouter(prefix="/api/v1/settlements", tags=["settlements"])


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


@router.post("", status_code=201)
async def create_settlement(
    body: SettlementCreate,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> SettlementCreated:
    return await _service(session, container).create(ctx, body, request_id=request_id)


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
