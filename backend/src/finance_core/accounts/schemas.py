"""What the accounts API accepts and returns."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from finance_core.schemas import ApiInput, ApiModel

AccountKindField = Literal["bank", "credit_card", "wallet", "cash", "other"]


class AccountView(ApiModel):
    id: uuid.UUID
    name: str
    kind: AccountKindField
    currency: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class AccountCreate(ApiInput):
    """A new account. Without a currency it takes the user's base currency."""

    name: str = Field(min_length=1, max_length=60)
    kind: AccountKindField
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class AccountUpdate(ApiInput):
    """Partial update: a field left out (or null) stays as it is.

    There is no `currency`: an account's currency is fixed when it is created, so sending
    one is rejected like any other unknown field.
    """

    name: str | None = Field(default=None, min_length=1, max_length=60)
    kind: AccountKindField | None = None
    is_archived: bool | None = None
