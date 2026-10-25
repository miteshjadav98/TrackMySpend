"""Conversation and message persistence (the chat transcript)."""

from __future__ import annotations

import base64
import binascii
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.clock import Clock
from finance_core.conversations.models import Conversation, Message
from finance_core.conversations.schemas import (
    ConversationPage,
    ConversationUpdate,
    ConversationView,
    MessagePage,
    MessageView,
)
from finance_core.errors import NotFoundError, ValidationFailedError
from finance_core.ids import uuid7
from finance_core.interactions import Interaction

logger = logging.getLogger(__name__)

_interaction_adapter: TypeAdapter[Interaction] = TypeAdapter(Interaction)


@dataclass(frozen=True, slots=True)
class HistoryItem:
    role: Literal["user", "assistant"]
    text: str


def _encode_cursor(moment: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps({"t": moment.isoformat(), "i": str(row_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        data = json.loads(base64.urlsafe_b64decode((cursor + "=" * (-len(cursor) % 4)).encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise ValidationFailedError(
            "Invalid pagination cursor", details={"field": "cursor"}
        ) from None


def parse_ui(raw: list[dict[str, Any]] | None) -> list[Interaction]:
    """Validate stored UI payloads; skip (and log) anything this version cannot render."""
    items: list[Interaction] = []
    for entry in raw or []:
        try:
            items.append(_interaction_adapter.validate_python(entry))
        except ValidationError:
            logger.warning("skipping unreadable ui payload", extra={"uiType": entry.get("type")})
    return items


def dump_ui(items: list[Interaction]) -> list[dict[str, Any]]:
    return [_interaction_adapter.dump_python(item, mode="json", by_alias=True) for item in items]


def message_view(row: Message) -> MessageView:
    return MessageView(
        id=row.id,
        role=row.role,
        content=row.content,
        ui=parse_ui(row.ui),
        status=row.status,
        reply_to_id=row.reply_to_id,
        client_message_id=row.client_message_id,
        created_at=row.created_at,
    )


def conversation_view(row: Conversation) -> ConversationView:
    return ConversationView.model_validate(row)


class ConversationService:
    def __init__(self, session: AsyncSession, *, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def create(self, user_id: uuid.UUID, title: str | None = None) -> ConversationView:
        now = self._clock.now()
        row = Conversation(user_id=user_id, title=title, status="active", last_message_at=now)
        self._session.add(row)
        await self._session.commit()
        return conversation_view(row)

    async def get_owned(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
        row = await self._session.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        if row is None:
            raise NotFoundError("Conversation not found")
        return row

    async def list_conversations(
        self,
        user_id: uuid.UUID,
        *,
        limit: int = 30,
        cursor: str | None = None,
        include_archived: bool = False,
    ) -> ConversationPage:
        limit = max(1, min(limit, 100))
        stmt = select(Conversation).where(Conversation.user_id == user_id)
        if not include_archived:
            stmt = stmt.where(Conversation.status == "active")
        if cursor:
            moment, row_id = _decode_cursor(cursor)
            stmt = stmt.where(
                tuple_(Conversation.last_message_at, Conversation.id) < tuple_(moment, row_id)
            )
        rows = (
            await self._session.scalars(
                stmt.order_by(Conversation.last_message_at.desc(), Conversation.id.desc()).limit(
                    limit + 1
                )
            )
        ).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = (
            _encode_cursor(rows[-1].last_message_at, rows[-1].id) if has_more and rows else None
        )
        return ConversationPage(items=[conversation_view(r) for r in rows], next_cursor=next_cursor)

    async def update(
        self, user_id: uuid.UUID, conversation_id: uuid.UUID, data: ConversationUpdate
    ) -> ConversationView:
        row = await self.get_owned(user_id, conversation_id)
        if data.title is not None:
            row.title = data.title
        if data.status is not None:
            row.status = data.status
        await self._session.commit()
        return conversation_view(row)

    async def delete(self, user_id: uuid.UUID, conversation_id: uuid.UUID) -> None:
        await self.get_owned(user_id, conversation_id)
        await self._session.execute(
            delete(Conversation).where(
                Conversation.id == conversation_id, Conversation.user_id == user_id
            )
        )
        await self._session.commit()

    async def messages(
        self,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        *,
        limit: int = 50,
        before: uuid.UUID | None = None,
    ) -> MessagePage:
        """Most recent `limit` messages (optionally older than `before`), oldest first."""
        await self.get_owned(user_id, conversation_id)
        limit = max(1, min(limit, 200))
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        if before is not None:
            anchor = await self._session.get(Message, before)
            if anchor is None or anchor.conversation_id != conversation_id:
                raise ValidationFailedError("Unknown message cursor", details={"field": "before"})
            stmt = stmt.where(
                tuple_(Message.created_at, Message.id) < (anchor.created_at, anchor.id)
            )
        rows = (
            await self._session.scalars(
                stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit + 1)
            )
        ).all()
        has_more = len(rows) > limit
        rows = list(reversed(rows[:limit]))
        return MessagePage(items=[message_view(r) for r in rows], has_more=has_more)

    async def history_window(
        self, conversation_id: uuid.UUID, *, limit: int, exclude_id: uuid.UUID | None = None
    ) -> list[HistoryItem]:
        """Bounded, text-only history for the model. The transcript stays the source of truth."""
        if limit <= 0:
            return []
        stmt = select(Message.role, Message.content).where(
            Message.conversation_id == conversation_id, Message.status == "completed"
        )
        if exclude_id is not None:
            stmt = stmt.where(Message.id != exclude_id)
        rows = (
            await self._session.execute(
                stmt.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
            )
        ).all()
        return [
            HistoryItem(role="assistant" if role == "assistant" else "user", text=content[:500])
            for role, content in reversed(rows)
        ]

    async def find_user_message(
        self, conversation_id: uuid.UUID, client_message_id: uuid.UUID
    ) -> Message | None:
        return await self._session.scalar(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.client_message_id == client_message_id,
            )
        )

    async def reply_to(self, message_id: uuid.UUID) -> Message | None:
        return await self._session.scalar(
            select(Message)
            .where(Message.reply_to_id == message_id, Message.role == "assistant")
            .order_by(Message.created_at.desc())
            .limit(1)
        )

    async def add_user_message(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        client_message_id: uuid.UUID,
        content: str,
        meta: dict[str, Any] | None = None,
    ) -> tuple[Message, bool]:
        """Insert idempotently on (conversation, client_message_id). Returns (row, created)."""
        inserted_id = await self._session.scalar(
            pg_insert(Message)
            .values(
                id=uuid7(),
                conversation_id=conversation_id,
                user_id=user_id,
                role="user",
                content=content,
                meta=meta,
                client_message_id=client_message_id,
                status="completed",
            )
            .on_conflict_do_nothing(index_elements=["conversation_id", "client_message_id"])
            .returning(Message.id)
        )
        await self._touch(conversation_id, title_hint=content if inserted_id else None)
        await self._session.commit()
        row = await self.find_user_message(conversation_id, client_message_id)
        assert row is not None
        return row, inserted_id is not None

    async def add_assistant_message(
        self,
        *,
        user_id: uuid.UUID,
        conversation_id: uuid.UUID,
        reply_to_id: uuid.UUID,
        content: str,
        ui: list[Interaction],
        meta: dict[str, Any] | None = None,
        status: Literal["completed", "failed"] = "completed",
    ) -> Message:
        row = Message(
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content=content,
            ui=dump_ui(ui) or None,
            meta=meta,
            reply_to_id=reply_to_id,
            status=status,
        )
        self._session.add(row)
        await self._touch(conversation_id, title_hint=None)
        await self._session.commit()
        return row

    async def _touch(self, conversation_id: uuid.UUID, *, title_hint: str | None) -> None:
        values: dict[str, Any] = {"last_message_at": self._clock.now()}
        await self._session.execute(
            update(Conversation).where(Conversation.id == conversation_id).values(**values)
        )
        if title_hint:
            title = " ".join(title_hint.split())
            title = title if len(title) <= 60 else title[:57].rstrip() + "…"
            await self._session.execute(
                update(Conversation)
                .where(Conversation.id == conversation_id, Conversation.title.is_(None))
                .values(title=title)
            )
