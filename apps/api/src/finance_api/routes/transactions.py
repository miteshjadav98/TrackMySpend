from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Header, Query, Response

from finance_api.deps import ContainerDep, RequestIdDep, SessionDep, UserContextDep
from finance_core.transactions.schemas import (
    SortField,
    TransactionCreate,
    TransactionPage,
    TransactionQuery,
    TransactionTypeField,
    TransactionUpdate,
    TransactionView,
)
from finance_core.transactions.service import TransactionService

router = APIRouter(prefix="/api/v1/transactions", tags=["transactions"])

IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        pattern=r"^[A-Za-z0-9._:-]{8,100}$",
        description="Client-generated key; repeating it returns the original transaction.",
    ),
]


def _service(session: SessionDep, container: ContainerDep) -> TransactionService:
    return TransactionService(session, clock=container.clock, generation=container.generation)


@router.get("")
async def list_transactions(
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    type: Annotated[TransactionTypeField | None, Query()] = None,
    category_id: Annotated[uuid.UUID | None, Query(alias="categoryId")] = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    min_amount: Annotated[Decimal | None, Query(alias="minAmount", gt=0)] = None,
    max_amount: Annotated[Decimal | None, Query(alias="maxAmount", gt=0)] = None,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    sort: Annotated[SortField, Query()] = "recent",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> TransactionPage:
    return await _service(session, container).search(
        ctx,
        TransactionQuery(
            type=type,
            category_id=category_id,
            date_from=date_from,
            date_to=date_to,
            text=q,
            min_amount=min_amount,
            max_amount=max_amount,
            currency=currency,
            sort=sort,
            limit=limit,
            cursor=cursor,
        ),
    )


@router.post(
    "",
    status_code=201,
    responses={200: {"model": TransactionView, "description": "Idempotent replay"}},
)
async def create_transaction(
    body: TransactionCreate,
    response: Response,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
    idempotency_key: IdempotencyKey = None,
) -> TransactionView:
    view, created = await _service(session, container).create(
        ctx,
        body,
        source="manual",
        # Namespaced so client keys can never collide with keys the agent generates.
        idempotency_key=f"api:{idempotency_key}" if idempotency_key else None,
        request_id=request_id,
    )
    if not created:
        response.status_code = 200
    return view


@router.get("/{transaction_id}")
async def get_transaction(
    transaction_id: uuid.UUID, ctx: UserContextDep, session: SessionDep, container: ContainerDep
) -> TransactionView:
    return await _service(session, container).get(ctx, transaction_id)


@router.patch("/{transaction_id}")
async def update_transaction(
    transaction_id: uuid.UUID,
    body: TransactionUpdate,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> TransactionView:
    return await _service(session, container).update(
        ctx, transaction_id, body, request_id=request_id
    )


@router.delete("/{transaction_id}", status_code=204)
async def delete_transaction(
    transaction_id: uuid.UUID,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> None:
    await _service(session, container).delete(ctx, transaction_id, request_id=request_id)


@router.post("/{transaction_id}/restore")
async def restore_transaction(
    transaction_id: uuid.UUID,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> TransactionView:
    return await _service(session, container).restore(ctx, transaction_id, request_id=request_id)
