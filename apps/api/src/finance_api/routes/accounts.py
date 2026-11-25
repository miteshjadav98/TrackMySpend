"""Accounts over HTTP: list, add and change. There is no delete: retired accounts are archived."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from finance_api.deps import ContainerDep, RequestIdDep, SessionDep, UserContextDep
from finance_core.accounts.balances import AccountBalanceService
from finance_core.accounts.schemas import (
    AccountBalanceView,
    AccountCreate,
    AccountOverview,
    AccountUpdate,
    BalanceLedger,
)
from finance_core.accounts.service import AccountService

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


@router.get("")
async def list_accounts(
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    include_archived: Annotated[bool, Query(alias="includeArchived")] = False,
) -> list[AccountBalanceView]:
    return await AccountBalanceService(session, container.clock).accounts(
        ctx, include_archived=include_archived
    )


@router.get("/overview")
async def overview(
    ctx: UserContextDep, session: SessionDep, container: ContainerDep
) -> AccountOverview:
    return await AccountBalanceService(session, container.clock).overview(ctx)


@router.get("/{account_id}/ledger")
async def ledger(
    account_id: uuid.UUID,
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BalanceLedger:
    return await AccountBalanceService(session, container.clock).ledger(
        ctx, account_id, limit, offset
    )


@router.post("", status_code=201)
async def create_account(
    body: AccountCreate,
    ctx: UserContextDep,
    session: SessionDep,
    request_id: RequestIdDep,
    container: ContainerDep,
) -> AccountBalanceView:
    row = await AccountService(session, clock=container.clock).create(
        ctx, body, request_id=request_id
    )
    await container.generation.bump(ctx.user_id)
    return await AccountBalanceService(session, container.clock).one(ctx, row.id)


@router.patch("/{account_id}")
async def update_account(
    account_id: uuid.UUID,
    body: AccountUpdate,
    ctx: UserContextDep,
    session: SessionDep,
    request_id: RequestIdDep,
    container: ContainerDep,
) -> AccountBalanceView:
    await AccountService(session, clock=container.clock).update(
        ctx, account_id, body, request_id=request_id
    )
    await container.generation.bump(ctx.user_id)
    return await AccountBalanceService(session, container.clock).one(ctx, account_id)
