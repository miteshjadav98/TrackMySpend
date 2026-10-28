"""Accounts over HTTP: list, add and change. There is no delete: retired accounts are archived."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from finance_api.deps import RequestIdDep, SessionDep, UserContextDep
from finance_core.accounts.schemas import AccountCreate, AccountUpdate, AccountView
from finance_core.accounts.service import AccountService

router = APIRouter(prefix="/api/v1/accounts", tags=["accounts"])


@router.get("")
async def list_accounts(
    ctx: UserContextDep,
    session: SessionDep,
    include_archived: Annotated[bool, Query(alias="includeArchived")] = False,
) -> list[AccountView]:
    return await AccountService(session).list_accounts(ctx, include_archived=include_archived)


@router.post("", status_code=201)
async def create_account(
    body: AccountCreate, ctx: UserContextDep, session: SessionDep, request_id: RequestIdDep
) -> AccountView:
    return await AccountService(session).create(ctx, body, request_id=request_id)


@router.patch("/{account_id}")
async def update_account(
    account_id: uuid.UUID,
    body: AccountUpdate,
    ctx: UserContextDep,
    session: SessionDep,
    request_id: RequestIdDep,
) -> AccountView:
    return await AccountService(session).update(ctx, account_id, body, request_id=request_id)
