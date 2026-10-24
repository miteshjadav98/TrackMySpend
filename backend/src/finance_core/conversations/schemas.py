from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from finance_core.interactions import Interaction, PendingInteraction, SuggestedPrompt
from finance_core.schemas import ApiInput, ApiModel


class ConversationView(ApiModel):
    id: uuid.UUID
    title: str | None
    status: Literal["active", "archived"]
    created_at: datetime
    last_message_at: datetime


class ConversationPage(ApiModel):
    items: list[ConversationView]
    next_cursor: str | None


class MessageView(ApiModel):
    id: uuid.UUID
    role: Literal["user", "assistant"]
    content: str
    ui: list[Interaction] = Field(default_factory=list)
    status: Literal["completed", "failed"]
    reply_to_id: uuid.UUID | None
    client_message_id: uuid.UUID | None
    created_at: datetime


class ConversationDetail(ApiModel):
    conversation: ConversationView
    messages: list[MessageView]
    has_more_messages: bool
    # The question the assistant is waiting on, if any. Survives refreshes and restarts
    # because it is read back from the durable workflow checkpoint.
    pending_interaction: PendingInteraction | None
    suggestions: list[SuggestedPrompt]


class MessagePage(ApiModel):
    items: list[MessageView]
    has_more: bool


class ConversationCreate(ApiInput):
    title: str | None = Field(default=None, max_length=200)


class ConversationUpdate(ApiInput):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["active", "archived"] | None = None
