"""Notices: the "Shared with you" messages a linked friend sees after someone else's change.

`NoticeWriter` is what the friend, shared-expense and settlement services call to leave a
notice. It only adds the row to the caller's session, so the notice is saved in the same
database transaction as the change it reports. `NoticeService` is the reading side: a user
lists their own notices and marks them read. Nobody ever sees another user's notice.

The row stores facts (who, what, how much), not text. The message is worded when it is read,
so the amount follows the reader's own locale.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.friends.models import Friend, Notice
from finance_core.friends.schemas import NoticeList, NoticeView, UnreadCount
from finance_core.ids import uuid7
from finance_core.money import format_money
from finance_core.users.context import UserContext
from finance_core.users.models import User

MAX_LIST = 50

SHARED_EXPENSE_ADDED = "shared_expense_added"
SHARED_EXPENSE_CHANGED = "shared_expense_changed"
SHARED_EXPENSE_DELETED = "shared_expense_deleted"
SETTLEMENT_RECORDED = "settlement_recorded"
SETTLEMENT_DELETED = "settlement_deleted"
INVITE_ACCEPTED = "invite_accepted"
INVITE_RECEIVED = "invite_received"


class NoticeWriter:
    """Leaves a notice for another user, inside the caller's database transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def notify(
        self,
        *,
        recipient_id: uuid.UUID,
        actor_id: uuid.UUID,
        kind: str,
        subject: str | None = None,
        amount_minor: int | None = None,
        currency: str | None = None,
        friend: Friend | None = None,
    ) -> None:
        """Tell `recipient_id` what `actor_id` did. The actor is named the way the recipient
        knows them: by their own friend row for the actor, else the actor's account name.
        Pass `friend` when the caller already holds that row."""
        if recipient_id == actor_id:  # nobody is told about their own act
            return
        friend = friend or await self._friend_row(recipient_id, actor_id)
        if friend is not None:
            actor_name: str | None = friend.name
        else:
            actor_name = await self._session.scalar(
                select(User.display_name).where(User.id == actor_id)
            )
        self._session.add(
            Notice(
                id=uuid7(),
                user_id=recipient_id,
                kind=kind,
                actor_name=actor_name or "Someone",
                friend_id=friend.id if friend else None,
                subject=subject,
                amount_minor=amount_minor,
                currency=currency,
            )
        )

    async def _friend_row(self, recipient_id: uuid.UUID, actor_id: uuid.UUID) -> Friend | None:
        return await self._session.scalar(
            select(Friend)
            .where(
                Friend.user_id == recipient_id,
                Friend.linked_user_id == actor_id,
                Friend.is_archived.is_(False),
            )
            .order_by(Friend.created_at, Friend.id)
            .limit(1)
        )


class NoticeService:
    """Lists and clears one user's own notices."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_notices(self, ctx: UserContext, *, limit: int = 20) -> NoticeList:
        """The most recent notices, newest first, with how many are still unread."""
        size = max(1, min(limit, MAX_LIST))
        rows = (
            await self._session.scalars(
                select(Notice)
                .where(Notice.user_id == ctx.user_id)
                .order_by(Notice.created_at.desc(), Notice.id.desc())
                .limit(size)
            )
        ).all()
        return NoticeList(
            unread_count=await self._unread_count(ctx),
            items=[_view(row, ctx.locale) for row in rows],
        )

    async def mark_read(self, ctx: UserContext, ids: Sequence[uuid.UUID] | None) -> UnreadCount:
        """Mark the given notices read, or every unread one when `ids` is None. Ids that are
        not the user's own are ignored, so another user's notice is never touched."""
        statement = update(Notice).where(Notice.user_id == ctx.user_id, Notice.read_at.is_(None))
        if ids is not None:
            statement = statement.where(Notice.id.in_(ids))
        await self._session.execute(statement.values(read_at=func.now()))
        await self._session.commit()
        return UnreadCount(unread_count=await self._unread_count(ctx))

    async def _unread_count(self, ctx: UserContext) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(Notice)
            .where(Notice.user_id == ctx.user_id, Notice.read_at.is_(None))
        )
        return int(count or 0)


def _view(row: Notice, locale: str) -> NoticeView:
    return NoticeView(
        id=row.id,
        kind=row.kind,
        message=_message(row, locale),
        friend_id=row.friend_id,
        is_read=row.read_at is not None,
        created_at=row.created_at,
    )


def _message(row: Notice, locale: str) -> str:
    who = row.actor_name
    what = row.subject or "a shared expense"
    amount = (
        format_money(row.amount_minor, row.currency, locale)
        if row.amount_minor is not None and row.currency
        else ""
    )
    messages = {
        SHARED_EXPENSE_ADDED: f"{who} added {what}: your share is {amount}",
        SHARED_EXPENSE_CHANGED: f"{who} changed {what}: your share is now {amount}",
        SHARED_EXPENSE_DELETED: f"{who} deleted {what}",
        SETTLEMENT_RECORDED: f"{who} recorded a settlement of {amount}",
        SETTLEMENT_DELETED: f"{who} deleted a settlement of {amount}",
        INVITE_ACCEPTED: f"{who} accepted your friend invite",
        INVITE_RECEIVED: f"{who} invited you to be friends",
    }
    return messages[row.kind]


__all__ = ["NoticeService", "NoticeWriter"]
