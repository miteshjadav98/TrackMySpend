"""Balances between a user and their friends, worked out in SQL.

Every shared expense and settlement that moves a balance is one signed line in a single query
(`balance_lines`). A balance is the sum of those lines per friend and currency, and a friend's
history is the same lines listed by date, so the two can never disagree.

A line is positive when it makes the friend owe the user more:
- the friend's share of an expense the user paid: +share
- the user's share of an expense the friend paid: -share
- a settlement the friend paid the user: -amount
- a settlement the user paid the friend: +amount

A linked friend's own records add the mirror lines, so both sides always agree: what a friend
recorded with the user counts for the user too, against the user's own friend row for them
(see `_lines_recorded_by_friends`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Select, and_, case, func, literal, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from finance_core.friends.models import Friend, Settlement, SharedExpense, SharedExpenseShare
from finance_core.friends.schemas import BalanceView, HistoryEntry
from finance_core.money import format_money, from_minor

SHARED_EXPENSE = "shared_expense"
SETTLEMENT = "settlement"


def balance_lines(user_id: uuid.UUID) -> Select[tuple[object, ...]]:
    """One row per shared expense share or settlement between the user and a friend.

    Columns: friend_id, currency, effect_minor, kind, entity_id, occurred_on, created_at, label.
    """
    friends_share_of_my_expense = (
        select(
            SharedExpenseShare.friend_id.label("friend_id"),
            SharedExpense.currency.label("currency"),
            SharedExpenseShare.amount_minor.label("effect_minor"),
            literal(SHARED_EXPENSE).label("kind"),
            SharedExpense.id.label("entity_id"),
            SharedExpense.occurred_on.label("occurred_on"),
            SharedExpense.created_at.label("created_at"),
            SharedExpense.description.label("label"),
        )
        .join(SharedExpense, SharedExpense.id == SharedExpenseShare.shared_expense_id)
        .where(
            SharedExpense.recorder_id == user_id,
            SharedExpense.payer_friend_id.is_(None),
            SharedExpenseShare.friend_id.is_not(None),
        )
    )
    my_share_of_friends_expense = (
        select(
            SharedExpense.payer_friend_id.label("friend_id"),
            SharedExpense.currency.label("currency"),
            (-SharedExpenseShare.amount_minor).label("effect_minor"),
            literal(SHARED_EXPENSE).label("kind"),
            SharedExpense.id.label("entity_id"),
            SharedExpense.occurred_on.label("occurred_on"),
            SharedExpense.created_at.label("created_at"),
            SharedExpense.description.label("label"),
        )
        .join(SharedExpense, SharedExpense.id == SharedExpenseShare.shared_expense_id)
        .where(
            SharedExpense.recorder_id == user_id,
            SharedExpense.payer_friend_id.is_not(None),
            SharedExpenseShare.friend_id.is_(None),
        )
    )
    settlements = select(
        Settlement.friend_id.label("friend_id"),
        Settlement.currency.label("currency"),
        case(
            (Settlement.paid_by_recorder, Settlement.amount_minor), else_=-Settlement.amount_minor
        ).label("effect_minor"),
        literal(SETTLEMENT).label("kind"),
        Settlement.id.label("entity_id"),
        Settlement.occurred_on.label("occurred_on"),
        Settlement.created_at.label("created_at"),
        Settlement.note.label("label"),
    ).where(Settlement.recorder_id == user_id)
    return union_all(  # type: ignore[return-value]
        friends_share_of_my_expense,
        my_share_of_friends_expense,
        settlements,
        *_lines_recorded_by_friends(user_id),
    )


def _lines_recorded_by_friends(user_id: uuid.UUID) -> list[Select[tuple[object, ...]]]:
    """The same balance as the linked friend sees it: what they recorded with this user.

    Their friend row for this user is `recorder_friend` (linked to the user); the user's own
    row for the recorder is `mine`, and is the friend the line belongs to. Every line is
    the mirror image of the recorder's: what makes the user owe more is negative here.
    """
    recorder_friend = aliased(Friend)
    mine = aliased(Friend)
    recorders_share = aliased(SharedExpenseShare)

    def with_recorder(query: Any, recorder_id: Any) -> Any:
        return query.join(
            mine,
            and_(
                mine.user_id == user_id,
                mine.linked_user_id == recorder_id,
                mine.is_archived.is_(False),
            ),
        )

    my_share_of_their_expense = with_recorder(
        select(
            mine.id.label("friend_id"),
            SharedExpense.currency.label("currency"),
            (-SharedExpenseShare.amount_minor).label("effect_minor"),
            literal(SHARED_EXPENSE).label("kind"),
            SharedExpense.id.label("entity_id"),
            SharedExpense.occurred_on.label("occurred_on"),
            SharedExpense.created_at.label("created_at"),
            SharedExpense.description.label("label"),
        )
        .select_from(SharedExpenseShare)
        .join(SharedExpense, SharedExpense.id == SharedExpenseShare.shared_expense_id)
        .join(recorder_friend, recorder_friend.id == SharedExpenseShare.friend_id),
        SharedExpense.recorder_id,
    ).where(recorder_friend.linked_user_id == user_id, SharedExpense.payer_friend_id.is_(None))
    their_share_of_my_expense = with_recorder(
        select(
            mine.id.label("friend_id"),
            SharedExpense.currency.label("currency"),
            recorders_share.amount_minor.label("effect_minor"),
            literal(SHARED_EXPENSE).label("kind"),
            SharedExpense.id.label("entity_id"),
            SharedExpense.occurred_on.label("occurred_on"),
            SharedExpense.created_at.label("created_at"),
            SharedExpense.description.label("label"),
        )
        .select_from(SharedExpense)
        .join(recorder_friend, recorder_friend.id == SharedExpense.payer_friend_id)
        .join(
            recorders_share,
            and_(
                recorders_share.shared_expense_id == SharedExpense.id,
                recorders_share.friend_id.is_(None),
            ),
        ),
        SharedExpense.recorder_id,
    ).where(recorder_friend.linked_user_id == user_id)
    their_settlements = with_recorder(
        select(
            mine.id.label("friend_id"),
            Settlement.currency.label("currency"),
            case(
                (Settlement.paid_by_recorder, -Settlement.amount_minor),
                else_=Settlement.amount_minor,
            ).label("effect_minor"),
            literal(SETTLEMENT).label("kind"),
            Settlement.id.label("entity_id"),
            Settlement.occurred_on.label("occurred_on"),
            Settlement.created_at.label("created_at"),
            Settlement.note.label("label"),
        )
        .select_from(Settlement)
        .join(recorder_friend, recorder_friend.id == Settlement.friend_id),
        Settlement.recorder_id,
    ).where(recorder_friend.linked_user_id == user_id)
    return [my_share_of_their_expense, their_share_of_my_expense, their_settlements]


async def balances_by_friend(
    session: AsyncSession, user_id: uuid.UUID, friend_ids: Sequence[uuid.UUID], locale: str
) -> dict[uuid.UUID, list[BalanceView]]:
    """Each friend's balance per currency, leaving out currencies that are settled up."""
    if not friend_ids:
        return {}
    lines = balance_lines(user_id).subquery("lines")
    total = func.sum(lines.c.effect_minor)
    rows = await session.execute(
        select(lines.c.friend_id, lines.c.currency, total)
        .where(lines.c.friend_id.in_(friend_ids))
        .group_by(lines.c.friend_id, lines.c.currency)
        .having(total != 0)
        .order_by(lines.c.friend_id, lines.c.currency)
    )
    result: dict[uuid.UUID, list[BalanceView]] = {}
    for friend_id, currency, amount_minor in rows.all():
        result.setdefault(friend_id, []).append(balance_view(currency, int(amount_minor), locale))
    return result


async def history_with(
    session: AsyncSession, user_id: uuid.UUID, friend_id: uuid.UUID, locale: str
) -> list[HistoryEntry]:
    """Every shared expense and settlement between the user and one friend, newest first."""
    lines = balance_lines(user_id).subquery("lines")
    rows = await session.execute(
        select(lines)
        .where(lines.c.friend_id == friend_id)
        .order_by(lines.c.occurred_on.desc(), lines.c.created_at.desc(), lines.c.entity_id.desc())
    )
    return [
        HistoryEntry(
            kind=row.kind,
            id=row.entity_id,
            occurred_on=row.occurred_on,
            label=row.label,
            currency=row.currency,
            effect_minor=row.effect_minor,
            effect_formatted=format_money(abs(row.effect_minor), row.currency, locale),
        )
        for row in rows.all()
    ]


async def balance_in(
    session: AsyncSession, user_id: uuid.UUID, friend_id: uuid.UUID, currency: str
) -> int:
    """The balance with one friend in one currency, in minor units (0 when settled up)."""
    lines = balance_lines(user_id).subquery("lines")
    total = await session.scalar(
        select(func.coalesce(func.sum(lines.c.effect_minor), 0)).where(
            lines.c.friend_id == friend_id, lines.c.currency == currency
        )
    )
    return int(total or 0)


def balance_view(currency: str, amount_minor: int, locale: str) -> BalanceView:
    return BalanceView(
        currency=currency,
        amount_minor=amount_minor,
        amount=from_minor(amount_minor, currency),
        formatted=format_money(abs(amount_minor), currency, locale),
    )


__all__ = ["balance_in", "balance_lines", "balance_view", "balances_by_friend", "history_with"]
