"""Friends over HTTP: the friends list, and the invites that link two users."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from finance_api.deps import ContainerDep, RequestIdDep, SessionDep, UserContextDep
from finance_core.friends.schemas import (
    FriendCreate,
    FriendDetail,
    FriendInviteView,
    FriendUpdate,
    FriendView,
    InviteAccept,
    InviteCodeSent,
)
from finance_core.friends.service import FriendService

router = APIRouter(prefix="/api/v1", tags=["friends"])


def _friend_service(session: SessionDep, container: ContainerDep) -> FriendService:
    # The clock and cache generation are for accepting an invite, which delivers past shares.
    return FriendService(session, clock=container.clock, generation=container.generation)


ServiceDep = Annotated[FriendService, Depends(_friend_service)]


@router.get("/friends")
async def list_friends(
    ctx: UserContextDep, service: ServiceDep, archived: Annotated[bool, Query()] = False
) -> list[FriendView]:
    return await service.list_friends(ctx, archived=archived)


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


@router.post("/friends/{friend_id}/unarchive")
async def unarchive_friend(
    friend_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> FriendView:
    return await service.unarchive(ctx, friend_id, request_id=request_id)


@router.delete("/friends/{friend_id}", status_code=204)
async def remove_friend(
    friend_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> Response:
    await service.remove(ctx, friend_id, request_id=request_id)
    return Response(status_code=204)


@router.get("/friend-invites")
async def list_incoming_invites(ctx: UserContextDep, service: ServiceDep) -> list[FriendInviteView]:
    return await service.list_incoming_invites(ctx)


@router.post("/friend-invites/{invite_id}/code", status_code=202)
async def send_invite_code(
    invite_id: uuid.UUID,
    ctx: UserContextDep,
    service: ServiceDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> InviteCodeSent:
    """Email a one-time code to the invited address; accepting needs it."""
    # Each request sends an email, so it is limited per user, resends included.
    await container.rate_limiter.hit(
        "invite-code",
        str(ctx.user_id),
        limit=container.settings.rate_limit_invite_code_per_hour,
        window_seconds=3600,
    )
    message = await service.send_invite_code(ctx, invite_id, request_id=request_id)
    await container.email_sender.send(message)
    return InviteCodeSent(email=message.to)


@router.post("/friend-invites/{invite_id}/accept")
async def accept_invite(
    invite_id: uuid.UUID,
    body: InviteAccept,
    ctx: UserContextDep,
    service: ServiceDep,
    request_id: RequestIdDep,
) -> FriendView:
    return await service.accept(ctx, invite_id, body.code, request_id=request_id)


@router.post("/friend-invites/{invite_id}/decline", status_code=204)
async def decline_invite(
    invite_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> Response:
    await service.decline(ctx, invite_id, request_id=request_id)
    return Response(status_code=204)
