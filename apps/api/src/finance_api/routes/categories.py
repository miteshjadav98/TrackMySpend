from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Query

from finance_api.deps import PrincipalDep, RequestIdDep, SessionDep
from finance_core.categories.schemas import CategoryCreate, CategoryView
from finance_core.categories.service import CategoryService

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


@router.get("")
async def list_categories(
    principal: PrincipalDep,
    session: SessionDep,
    kind: Annotated[Literal["expense", "income"] | None, Query()] = None,
) -> list[CategoryView]:
    return await CategoryService(session).list_visible(principal.user_id, kind)


@router.post("", status_code=201)
async def create_category(
    body: CategoryCreate, principal: PrincipalDep, session: SessionDep, request_id: RequestIdDep
) -> CategoryView:
    return await CategoryService(session).create(principal.user_id, body, request_id=request_id)
