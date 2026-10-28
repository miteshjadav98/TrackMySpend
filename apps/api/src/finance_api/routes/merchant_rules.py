"""Merchant rules in Settings: list the rules MoneyMoney has learned, change and forget them."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query

from finance_api.deps import ContainerDep, PrincipalDep, RequestIdDep, SessionDep
from finance_core.merchants.schemas import (
    MerchantRulePage,
    MerchantRuleQuery,
    MerchantRuleTypeField,
    MerchantRuleUpdate,
    MerchantRuleView,
)
from finance_core.merchants.service import MerchantRuleService

router = APIRouter(prefix="/api/v1/merchant-rules", tags=["merchant rules"])


def _service(session: SessionDep, container: ContainerDep) -> MerchantRuleService:
    return MerchantRuleService(session, clock=container.clock)


@router.get("")
async def list_merchant_rules(
    principal: PrincipalDep,
    session: SessionDep,
    container: ContainerDep,
    type: Annotated[MerchantRuleTypeField | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=100, description="Part of a merchant name")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
) -> MerchantRulePage:
    return await _service(session, container).search(
        principal.user_id, MerchantRuleQuery(type=type, merchant=q, limit=limit, cursor=cursor)
    )


@router.patch("/{rule_id}")
async def change_merchant_rule(
    rule_id: uuid.UUID,
    body: MerchantRuleUpdate,
    principal: PrincipalDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> MerchantRuleView:
    return await _service(session, container).change_category(
        principal.user_id, rule_id, body.category_id, request_id=request_id
    )


@router.delete("/{rule_id}", status_code=204)
async def forget_merchant_rule(
    rule_id: uuid.UUID,
    principal: PrincipalDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> None:
    await _service(session, container).forget(principal.user_id, rule_id, request_id=request_id)
