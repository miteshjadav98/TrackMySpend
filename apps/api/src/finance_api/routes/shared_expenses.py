"""Shared expenses over HTTP, from the point of view of the user who recorded them."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Response

from finance_api.deps import ContainerDep, RequestIdDep, SessionDep, UserContextDep
from finance_core.friends.schemas import (
    SharedExpenseCreate,
    SharedExpenseUpdate,
    SharedExpenseView,
)
from finance_core.friends.shared_expenses import SharedExpenseService

router = APIRouter(prefix="/api/v1/shared-expenses", tags=["shared-expenses"])


def _service(session: SessionDep, container: ContainerDep) -> SharedExpenseService:
    return SharedExpenseService(session, clock=container.clock, generation=container.generation)


@router.get("")
async def list_shared_expenses(
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[SharedExpenseView]:
    return await _service(session, container).list_shared(
        ctx, date_from=date_from, date_to=date_to, limit=limit
    )


@router.post("", status_code=201)
async def create_shared_expense(
    body: SharedExpenseCreate,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> SharedExpenseView:
    return await _service(session, container).create(ctx, body, request_id=request_id)


@router.get("/{shared_expense_id}")
async def get_shared_expense(
    shared_expense_id: uuid.UUID, ctx: UserContextDep, session: SessionDep, container: ContainerDep
) -> SharedExpenseView:
    return await _service(session, container).get(ctx, shared_expense_id)


@router.put("/{shared_expense_id}")
async def update_shared_expense(
    shared_expense_id: uuid.UUID,
    body: SharedExpenseUpdate,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> SharedExpenseView:
    return await _service(session, container).update(
        ctx, shared_expense_id, body, request_id=request_id
    )


@router.delete("/{shared_expense_id}", status_code=204)
async def delete_shared_expense(
    shared_expense_id: uuid.UUID,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> Response:
    await _service(session, container).delete(ctx, shared_expense_id, request_id=request_id)
    return Response(status_code=204)
