"""Notices over HTTP: the "Shared with you" list and marking it read."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from finance_api.deps import SessionDep, UserContextDep
from finance_core.friends.notices import NoticeService
from finance_core.friends.schemas import NoticeList, NoticesRead, UnreadCount

router = APIRouter(prefix="/api/v1/notices", tags=["notices"])


@router.get("")
async def list_notices(
    ctx: UserContextDep,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> NoticeList:
    return await NoticeService(session).list_notices(ctx, limit=limit)


@router.post("/read")
async def mark_notices_read(
    body: NoticesRead, ctx: UserContextDep, session: SessionDep
) -> UnreadCount:
    return await NoticeService(session).mark_read(ctx, body.ids)
