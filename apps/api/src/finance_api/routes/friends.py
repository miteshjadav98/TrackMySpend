"""Friends over HTTP: the friends list, and the invites that link two users."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response

from finance_api.deps import ContainerDep, RequestIdDep, SessionDep, UserContextDep
from finance_core.friends.schemas import (
    FriendCreate,
    FriendDetail,
    FriendInviteView,
    FriendUpdate,
    FriendView,
)
from finance_core.friends.service import FriendService

router = APIRouter(prefix="/api/v1", tags=["friends"])


def _friend_service(session: SessionDep, container: ContainerDep) -> FriendService:
    # The clock and cache generation are for accepting an invite, which delivers past shares.
    return FriendService(session, clock=container.clock, generation=container.generation)


ServiceDep = Annotated[FriendService, Depends(_friend_service)]


@router.get("/friends")
async def list_friends(ctx: UserContextDep, service: ServiceDep) -> list[FriendView]:
    return await service.list_friends(ctx)


@router.get("/friends/{friend_id}")
async def get_friend(
    friend_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep
) -> FriendDetail:
    return await service.detail(ctx, friend_id)


@router.post("/friends", status_code=201)
async def add_friend(
    body: FriendCreate, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> FriendView:
    return await service.add(ctx, body, request_id=request_id)


@router.patch("/friends/{friend_id}")
async def update_friend(
    friend_id: uuid.UUID,
    body: FriendUpdate,
    ctx: UserContextDep,
    service: ServiceDep,
    request_id: RequestIdDep,
) -> FriendView:
    return await service.update(ctx, friend_id, body, request_id=request_id)


@router.delete("/friends/{friend_id}", status_code=204)
async def remove_friend(
    friend_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> Response:
    await service.remove(ctx, friend_id, request_id=request_id)
    return Response(status_code=204)


@router.get("/friend-invites")
async def list_incoming_invites(ctx: UserContextDep, service: ServiceDep) -> list[FriendInviteView]:
    return await service.list_incoming_invites(ctx)


@router.post("/friend-invites/{invite_id}/accept")
async def accept_invite(
    invite_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> FriendView:
    return await service.accept(ctx, invite_id, request_id=request_id)


@router.post("/friend-invites/{invite_id}/decline", status_code=204)
async def decline_invite(
    invite_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> Response:
    await service.decline(ctx, invite_id, request_id=request_id)
    return Response(status_code=204)
