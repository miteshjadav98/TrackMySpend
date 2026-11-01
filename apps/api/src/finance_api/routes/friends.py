"""Friends over HTTP: the friends list, and the invites that link two users."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Response

from finance_api.deps import RequestIdDep, SessionDep, UserContextDep
from finance_core.friends.schemas import (
    FriendCreate,
    FriendDetail,
    FriendInviteView,
    FriendUpdate,
    FriendView,
)
from finance_core.friends.service import FriendService

router = APIRouter(prefix="/api/v1", tags=["friends"])


@router.get("/friends")
async def list_friends(ctx: UserContextDep, session: SessionDep) -> list[FriendView]:
    return await FriendService(session).list_friends(ctx)


@router.get("/friends/{friend_id}")
async def get_friend(
    friend_id: uuid.UUID, ctx: UserContextDep, session: SessionDep
) -> FriendDetail:
    return await FriendService(session).detail(ctx, friend_id)


@router.post("/friends", status_code=201)
async def add_friend(
    body: FriendCreate, ctx: UserContextDep, session: SessionDep, request_id: RequestIdDep
) -> FriendView:
    return await FriendService(session).add(ctx, body, request_id=request_id)


@router.patch("/friends/{friend_id}")
async def update_friend(
    friend_id: uuid.UUID,
    body: FriendUpdate,
    ctx: UserContextDep,
    session: SessionDep,
    request_id: RequestIdDep,
) -> FriendView:
    return await FriendService(session).update(ctx, friend_id, body, request_id=request_id)


@router.delete("/friends/{friend_id}", status_code=204)
async def remove_friend(
    friend_id: uuid.UUID, ctx: UserContextDep, session: SessionDep, request_id: RequestIdDep
) -> Response:
    await FriendService(session).remove(ctx, friend_id, request_id=request_id)
    return Response(status_code=204)


@router.get("/friend-invites")
async def list_incoming_invites(ctx: UserContextDep, session: SessionDep) -> list[FriendInviteView]:
    return await FriendService(session).list_incoming_invites(ctx)


@router.post("/friend-invites/{invite_id}/accept")
async def accept_invite(
    invite_id: uuid.UUID, ctx: UserContextDep, session: SessionDep, request_id: RequestIdDep
) -> FriendView:
    return await FriendService(session).accept(ctx, invite_id, request_id=request_id)


@router.post("/friend-invites/{invite_id}/decline", status_code=204)
async def decline_invite(
    invite_id: uuid.UUID, ctx: UserContextDep, session: SessionDep, request_id: RequestIdDep
) -> Response:
    await FriendService(session).decline(ctx, invite_id, request_id=request_id)
    return Response(status_code=204)
