from __future__ import annotations

from fastapi import APIRouter

from finance_api.deps import PrincipalDep, RequestIdDep, SessionDep
from finance_core.users.schemas import MeView, ProfileUpdate
from finance_core.users.service import UserService

router = APIRouter(prefix="/api/v1/me", tags=["profile"])


@router.get("")
async def get_me(principal: PrincipalDep, session: SessionDep) -> MeView:
    return await UserService(session).me(principal.user_id)


@router.patch("/profile")
async def update_profile(
    body: ProfileUpdate, principal: PrincipalDep, session: SessionDep, request_id: RequestIdDep
) -> MeView:
    return await UserService(session).update_profile(principal.user_id, body, request_id=request_id)
