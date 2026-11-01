"""Settlement service: the only code that writes settlements.

The rules it enforces:
- A settlement is between the user and one of their own friends (anyone else's is a 404), in
  one currency, for a positive amount, dated today or earlier.
- It is not a transaction: it moves the balance with that friend and nothing in summaries.
- More than is owed is allowed; the reply flags it so the user can check, because the balance
  then points the other way.
- A settlement shows on both sides: the linked friend lists it too, from their own point of
  view (direction flipped, named by their own friend row). Only whoever recorded it deletes
  it; anyone else gets a 404.
- Each write and its audit event, for the recorder and a linked friend, are saved in one
  database transaction.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from finance_core.accounts.schemas import AccountRef
from finance_core.accounts.service import AccountService
from finance_core.audit.service import record_audit
from finance_core.clock import Clock
from finance_core.dates import EARLIEST_ALLOWED_DATE
from finance_core.errors import NotFoundError, ValidationFailedError
from finance_core.friends.balances import balance_in
from finance_core.friends.models import Friend, Settlement
from finance_core.friends.schemas import (
    SettlementCreate,
    SettlementCreated,
    SettlementFriend,
    SettlementView,
)
from finance_core.ids import uuid7
from finance_core.money import (
    SUPPORTED_CURRENCIES,
    MoneyError,
    format_money,
    from_minor,
    to_minor,
)
from finance_core.users.context import UserContext

MAX_LIST = 200


class SettlementService:
    """Records, lists and deletes the settlements a user recorded."""

    def __init__(self, session: AsyncSession, *, clock: Clock) -> None:
        self._session = session
        self._clock = clock
        self._accounts = AccountService(session)

    async def create(
        self, ctx: UserContext, data: SettlementCreate, *, request_id: str | None = None
    ) -> SettlementCreated:
        """Record a settlement and say whether it was more than was owed."""
        friend = await self._owned_friend(ctx, data.friend_id)
        currency = (data.currency or ctx.base_currency).upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise ValidationFailedError(
                f"Unsupported currency: {currency}", details={"field": "currency"}
            )
        try:
            amount_minor = to_minor(data.amount, currency)
        except MoneyError as error:
            raise ValidationFailedError(str(error), details={"field": "amount"}) from None
        today = ctx.today(self._clock)
        occurred_on = data.occurred_on or today
        if occurred_on > today:
            raise ValidationFailedError(
                "The date can't be in the future.", details={"field": "occurredOn"}
            )
        if occurred_on < EARLIEST_ALLOWED_DATE:
            raise ValidationFailedError(
                "That date is too far in the past.", details={"field": "occurredOn"}
            )
        account_id = None
        if data.account_id is not None:
            picked = await self._accounts.pick_for_transaction(
                ctx, data.account_id, field="accountId"
            )
            account_id = picked.id

        paid_by_you = data.direction == "you_paid_friend"
        balance_before = await balance_in(self._session, ctx.user_id, friend.id, currency)
        # What this payment is meant to clear: what the friend owes (they paid me), or what I
        # owe (I paid them). Anything beyond that, or against that direction, flips the balance.
        owed_this_way = max(-balance_before if paid_by_you else balance_before, 0)
        exceeds = amount_minor > owed_this_way

        settlement = Settlement(
            id=uuid7(),  # set here, not at flush, so the audit event can name it
            recorder_id=ctx.user_id,
            friend_id=friend.id,
            paid_by_recorder=paid_by_you,
            amount_minor=amount_minor,
            currency=currency,
            occurred_on=occurred_on,
            note=(data.note or "").strip() or None,
            recorder_account_id=account_id,
        )
        self._session.add(settlement)
        self._audit(ctx.user_id, friend, "settlement.created", settlement, request_id)
        await self._session.commit()
        await self._session.refresh(settlement)

        view = (await self._views(ctx, [(settlement, friend)]))[0]
        warning = None
        if exceeds:
            owed_text = format_money(owed_this_way, currency, ctx.locale)
            who = f"you owed {friend.name}" if paid_by_you else f"{friend.name} owed you"
            warning = (
                f"That is more than {who} ({owed_text}), so the balance with {friend.name} "
                "now points the other way."
            )
        return SettlementCreated(**view.model_dump(), exceeds_balance=exceeds, warning=warning)

    async def list_settlements(
        self, ctx: UserContext, *, friend_id: uuid.UUID | None = None, limit: int = 100
    ) -> list[SettlementView]:
        """Settlements with the user, newest first, optionally with one friend: the ones they
        recorded and the ones a linked friend recorded with them."""
        recorded = select(Settlement, Friend).join(Friend, Friend.id == Settlement.friend_id)
        recorded = recorded.where(Settlement.recorder_id == ctx.user_id)
        # `mine` is the user's own friend row for the recorder, so the friend is named by it.
        recorder_friend = aliased(Friend)
        mine = aliased(Friend)
        recorded_by_friend = (
            select(Settlement, mine)
            .join(recorder_friend, recorder_friend.id == Settlement.friend_id)
            .join(
                mine,
                and_(
                    mine.user_id == ctx.user_id,
                    mine.linked_user_id == Settlement.recorder_id,
                    mine.is_archived.is_(False),
                ),
            )
            .where(recorder_friend.linked_user_id == ctx.user_id)
        )
        if friend_id is not None:
            recorded = recorded.where(Settlement.friend_id == friend_id)
            recorded_by_friend = recorded_by_friend.where(mine.id == friend_id)
        size = max(1, min(limit, MAX_LIST))
        pairs = [
            (settlement, friend)
            for query in (recorded, recorded_by_friend)
            for settlement, friend in (await self._session.execute(query)).all()
        ]
        pairs.sort(key=lambda pair: (pair[0].occurred_on, pair[0].id), reverse=True)
        return await self._views(ctx, pairs[:size])

    async def delete(
        self, ctx: UserContext, settlement_id: uuid.UUID, *, request_id: str | None = None
    ) -> None:
        """Delete a settlement the user recorded; the balance goes back as it was."""
        settlement = await self._session.scalar(
            select(Settlement).where(
                Settlement.id == settlement_id, Settlement.recorder_id == ctx.user_id
            )
        )
        if settlement is None:  # someone else's, or never existed
            raise NotFoundError("Settlement not found")
        friend = await self._session.get(Friend, settlement.friend_id)
        assert friend is not None  # a settlement's friend is archived, never deleted
        self._audit(ctx.user_id, friend, "settlement.deleted", settlement, request_id)
        await self._session.delete(settlement)
        await self._session.commit()

    # -- helpers --------------------------------------------------------------------------

    async def _owned_friend(self, ctx: UserContext, friend_id: uuid.UUID) -> Friend:
        # An archived friend takes no new settlements, like no new shared expenses.
        friend = await self._session.scalar(
            select(Friend).where(
                Friend.id == friend_id,
                Friend.user_id == ctx.user_id,
                Friend.is_archived.is_(False),
            )
        )
        if friend is None:
            raise NotFoundError("Friend not found")
        return friend

    def _audit(
        self,
        ctx_user_id: uuid.UUID,
        friend: Friend,
        action: str,
        settlement: Settlement,
        request_id: str | None,
    ) -> None:
        """Audit the change for the recorder and, when the friend is linked, for them too."""
        data: dict[str, Any] = {
            "paidByRecorder": settlement.paid_by_recorder,
            "amountMinor": settlement.amount_minor,
            "currency": settlement.currency,
            "occurredOn": settlement.occurred_on.isoformat(),
        }
        records = [(ctx_user_id, {**data, "friendId": str(settlement.friend_id)})]
        if friend.linked_user_id is not None:
            # The friend's log never names the recorder's own friend row.
            records.append((friend.linked_user_id, {**data, "recordedBy": str(ctx_user_id)}))
        for user_id, event_data in records:
            record_audit(
                self._session, user_id=user_id, actor="user", action=action,
                entity_type="settlement", entity_id=settlement.id, data=event_data,
                request_id=request_id,
            )  # fmt: skip

    async def _views(
        self, ctx: UserContext, pairs: Sequence[tuple[Settlement, Friend]]
    ) -> list[SettlementView]:
        """Each settlement from the user's side: `friend` is the user's own friend row for the
        other person, so the direction and account are read from the user's side too."""
        accounts: dict[uuid.UUID, AccountRef] = {}
        views: list[SettlementView] = []
        for row, friend in pairs:
            mine = row.recorder_id == ctx.user_id
            account_id = row.recorder_account_id if mine else row.friend_account_id
            if account_id is not None and account_id not in accounts:
                account = await self._accounts.get(ctx, account_id, field="accountId")
                accounts[account_id] = AccountRef(
                    id=account.id, name=account.name, kind=account.kind
                )
            paid_by_you = row.paid_by_recorder == mine
            views.append(
                SettlementView(
                    id=row.id,
                    friend=SettlementFriend(id=friend.id, name=friend.name),
                    direction="you_paid_friend" if paid_by_you else "friend_paid_you",
                    amount=from_minor(row.amount_minor, row.currency),
                    amount_minor=row.amount_minor,
                    currency=row.currency,
                    amount_formatted=format_money(row.amount_minor, row.currency, ctx.locale),
                    occurred_on=row.occurred_on,
                    note=row.note,
                    account=accounts.get(account_id) if account_id else None,
                    created_at=row.created_at,
                )
            )
        return views


__all__ = ["SettlementService"]
