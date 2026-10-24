from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from finance_core.schemas import ApiInput, ApiModel

CategoryKindField = Literal["expense", "income"]


class CategoryView(ApiModel):
    id: uuid.UUID
    slug: str
    name: str
    kind: CategoryKindField
    icon: str | None
    is_system: bool


class CategoryCreate(ApiInput):
    name: str = Field(min_length=1, max_length=64)
    kind: CategoryKindField
    icon: str | None = Field(default=None, max_length=32)
