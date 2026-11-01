"""What the friends API accepts and returns."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, Field

from finance_core.schemas import ApiInput, ApiModel

InviteStatusField = Literal["pending", "declined"]


class FriendView(ApiModel):
    """A friend as clients see them. `invite_status` is set while an invite is waiting for an
    answer or was declined; a linked friend has none."""

    id: uuid.UUID
    name: str
    email: str | None
    is_linked: bool
    invite_status: InviteStatusField | None
    created_at: datetime
    updated_at: datetime


class FriendCreate(ApiInput):
    """A new friend. With an email, an invite goes to whoever owns that email."""

    name: str = Field(min_length=1, max_length=80)
    email: EmailStr | None = None


class FriendUpdate(ApiInput):
    """Partial update. A name left out stays; an email sent as null is cleared."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    email: EmailStr | None = None


class FriendInviteView(ApiModel):
    """An invite waiting for the signed-in user to accept or decline."""

    id: uuid.UUID
    from_name: str
    from_email: str
    created_at: datetime
