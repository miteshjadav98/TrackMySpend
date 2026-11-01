"""The merchant rule contracts: how Settings lists, changes and forgets rules."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from finance_core.categories.schemas import CategoryRef
from finance_core.schemas import ApiInput, ApiModel

MerchantRuleTypeField = Literal["expense", "income"]


class MerchantRuleView(ApiModel):
    """One learned rule: the merchant, the category it files them under, and how often."""

    id: uuid.UUID
    merchant: str
    type: MerchantRuleTypeField
    category: CategoryRef
    times_used: int
    last_used_at: datetime


class MerchantRulePage(ApiModel):
    items: list[MerchantRuleView]
    next_cursor: str | None


class MerchantRuleUpdate(ApiInput):
    """A change to a rule: the category its merchant is filed under from now on."""

    category_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class MerchantRuleQuery:
    type: MerchantRuleTypeField | None = None
    merchant: str | None = None  # matched anywhere in the merchant name
    limit: int = 50
    cursor: str | None = None
