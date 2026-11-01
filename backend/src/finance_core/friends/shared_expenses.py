"""Shared expense service: the only code that writes shared expenses and their shares.

The rules it enforces:
- Only the recorder sees, edits or deletes a shared expense; anyone else gets a 404.
- The recorder is always a participant, with at least one friend, and nobody appears twice.
- Participants are the recorder's own friends. An archived friend cannot join a new shared
  expense, but stays in one they were already part of.
- When a friend paid, only the recorder and that friend take part.
- Shares are whole minor units that add up to the total: an equal split gives everyone the
  floor and the payer the leftover; exact amounts must sum to the total.
- The recorder's share is saved as an ordinary expense transaction, so summaries count the
  share. So is each linked friend's (see `share_delivery`). The shared expense, its shares,
  every share transaction and the audit event for each affected user are written in one
  database transaction.
- A participant who is a linked user can read the shared expense (named the way they know
  people, with nothing of the recorder's private fields) but never change it.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.cache.primitives import UserDataGeneration
from finance_core.clock import Clock
from finance_core.errors import NotFoundError, ValidationFailedError
from finance_core.friends.models import Friend, SharedExpense, SharedExpenseShare
from finance_core.friends.schemas import (
    ParticipantInput,
    PersonView,
    SharedExpenseCreate,
    SharedExpenseUpdate,
    SharedExpenseView,
    SharedExpenseWrite,
    ShareView,
)
from finance_core.friends.share_delivery import ShareDelivery
from finance_core.friends.splits import equal_split, exact_split
from finance_core.ids import uuid7
from finance_core.money import (
    SUPPORTED_CURRENCIES,
    MoneyError,
    format_money,
    from_minor,
    to_minor,
)
from finance_core.transactions.models import Transaction
from finance_core.transactions.schemas import NewTransaction, TransactionCreate
from finance_core.transactions.service import TransactionService
from finance_core.users.context import UserContext
from finance_core.users.models import User

# Keys of a split: the recorder is None, a friend is their id.
type PersonKey = uuid.UUID | None

YOU = "You"
MAX_LIST = 100


def _participants_error(message: str) -> ValidationFailedError:
    return ValidationFailedError(message, details={"field": "participants"})


class SharedExpenseService:
    """Records, shows, edits and deletes the shared expenses a user recorded."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock,
        generation: UserDataGeneration | None = None,
    ) -> None:
        self._session = session
        self._transactions = TransactionService(session, clock=clock, generation=generation)
        self._delivery = ShareDelivery(session, clock=clock)

    # -- writes ---------------------------------------------------------------------------

    async def create(
        self,
        ctx: UserContext,
        data: SharedExpenseCreate,
        *,
        request_id: str | None = None,
        source: str = "api",
        source_ref: str | None = None,
    ) -> SharedExpenseView:
        """Record a shared expense and the recorder's share of it. The chat passes its message
        as `source_ref`, so a retried message finds the share it already saved."""
        plan = await self._plan(ctx, data, existing=None)
        my_share = await self._transactions.resolve(
            ctx,
            TransactionCreate(
                type="expense",
                amount=from_minor(plan.shares[None], plan.currency),
                currency=plan.currency,
                occurred_on=data.occurred_on,
                category_id=data.category_id,
                account_id=data.account_id,
                description=data.description,
                merchant=data.merchant,
            ),
        )
        expense = SharedExpense(
            id=uuid7(),  # set here, not at flush, so the audit event and shares can name it
            recorder_id=ctx.user_id,
            payer_friend_id=data.payer_friend_id,
            total_minor=plan.total_minor,
            currency=plan.currency,
            occurred_on=my_share.occurred_on,
            description=my_share.description,
            merchant=my_share.merchant,
        )
        self._session.add(expense)
        await self._session.flush()  # the expense row must exist before shares point at it
        self._add_shares(expense.id, plan.shares)
        linked = await self._linked_users(plan.shares)
        await self._create_share_transactions(
            ctx, expense, my_share, plan.shares, linked, request_id, source, source_ref
        )
        self._audit_all(
            [ctx.user_id, *linked.values()], "shared_expense.created", expense.id,
            self._snapshot(expense, plan.shares), request_id,
        )  # fmt: skip
        await self._session.commit()
        await self._bump_generations([ctx.user_id, *linked.values()])
        return await self.get(ctx, expense.id)

    async def update(
        self,
        ctx: UserContext,
        shared_expense_id: uuid.UUID,
        data: SharedExpenseUpdate,
        *,
        request_id: str | None = None,
    ) -> SharedExpenseView:
        """Replace the bill and split, and move the recorder's share transaction with it."""
        expense = await self._owned(ctx, shared_expense_id)
        before = self._snapshot(expense, await self._share_amounts(expense.id))
        share_row = await self._transactions.share_row(ctx.user_id, expense.id)
        plan = await self._plan(ctx, data, existing=expense.id)
        # The share keeps its own category and account; resolve checks the new date and amount.
        my_share = await self._transactions.resolve(
            ctx,
            TransactionCreate(
                type="expense",
                amount=from_minor(plan.shares[None], plan.currency),
                currency=plan.currency,
                occurred_on=data.occurred_on,
                category_id=share_row.category_id,
                account_id=share_row.account_id,
                description=data.description,
                merchant=data.merchant,
            ),
            unchanged_from=share_row,
        )
        expense.payer_friend_id = data.payer_friend_id
        expense.total_minor = plan.total_minor
        expense.currency = plan.currency
        expense.occurred_on = my_share.occurred_on
        expense.description = my_share.description
        expense.merchant = my_share.merchant
        # Deleted first and flushed, so the replacement rows cannot trip the one-share-per-person
        # indexes (a flush runs inserts before deletes).
        await self._session.execute(
            delete(SharedExpenseShare).where(SharedExpenseShare.shared_expense_id == expense.id)
        )
        self._add_shares(expense.id, plan.shares)
        self._transactions.change_share_row(
            ctx.user_id,
            share_row,
            amount_minor=my_share.amount_minor,
            currency=my_share.currency,
            occurred_on=my_share.occurred_on,
            description=my_share.description,
            merchant=my_share.merchant,
            request_id=request_id,
        )
        affected = await self._sync_friend_shares(ctx, expense, plan, request_id)
        self._audit_all(
            [ctx.user_id, *affected], "shared_expense.updated", expense.id,
            {"before": before, "after": self._snapshot(expense, plan.shares)}, request_id,
        )  # fmt: skip
        await self._session.commit()
        await self._bump_generations([ctx.user_id, *affected])
        return await self.get(ctx, expense.id)

    async def delete(
        self, ctx: UserContext, shared_expense_id: uuid.UUID, *, request_id: str | None = None
    ) -> None:
        """Delete the shared expense, its shares and the recorder's share transaction."""
        expense = await self._owned(ctx, shared_expense_id)
        snapshot = self._snapshot(expense, await self._share_amounts(expense.id))
        rows = await self._share_rows(expense.id)
        for row in rows:  # the recorder's and every linked friend's
            await self._transactions.remove_share_row(row.user_id, row, request_id=request_id)
        # Flushed first: the transactions point at the expense, and the expense must go last.
        await self._session.flush()
        await self._session.delete(expense)  # its shares go with it (ON DELETE CASCADE)
        users = _users_of(ctx, rows)
        self._audit_all(
            users, "shared_expense.deleted", expense.id, {"before": snapshot}, request_id
        )
        await self._session.commit()
        await self._bump_generations(users)

    # -- reads ----------------------------------------------------------------------------

    async def get(self, ctx: UserContext, shared_expense_id: uuid.UUID) -> SharedExpenseView:
        """A shared expense the user recorded or takes part in; anyone else gets a 404."""
        expense = await self._session.scalar(
            select(SharedExpense).where(
                SharedExpense.id == shared_expense_id, self._can_see(ctx.user_id)
            )
        )
        if expense is None:
            raise NotFoundError("Shared expense not found")
        return (await self._views(ctx, [expense]))[0]

    async def list_shared(
        self,
        ctx: UserContext,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 50,
    ) -> list[SharedExpenseView]:
        """The shared expenses the user recorded or takes part in, newest first."""
        query = select(SharedExpense).where(self._can_see(ctx.user_id))
        if date_from:
            query = query.where(SharedExpense.occurred_on >= date_from)
        if date_to:
            query = query.where(SharedExpense.occurred_on <= date_to)
        rows = (
            await self._session.scalars(
                query.order_by(SharedExpense.occurred_on.desc(), SharedExpense.id.desc()).limit(
                    max(1, min(limit, MAX_LIST))
                )
            )
        ).all()
        return await self._views(ctx, rows)

    # -- linked friends' shares --------------------------------------------------------------

    async def _create_share_transactions(
        self,
        ctx: UserContext,
        expense: SharedExpense,
        my_share: NewTransaction,
        shares: dict[PersonKey, int],
        linked: dict[uuid.UUID, uuid.UUID],
        request_id: str | None,
        source: str,
        source_ref: str | None,
    ) -> None:
        """Give the recorder and every participant who is a linked user their share."""
        await self._transactions.add_share_row(
            ctx.user_id, my_share, shared_expense_id=expense.id, request_id=request_id,
            source=source, source_ref=source_ref,
        )  # fmt: skip
        # Flushed so the friends' delivery can read the category the recorder chose.
        await self._session.flush()
        for friend_id, user_id in linked.items():
            await self._delivery.deliver(
                expense, user_id=user_id, amount_minor=shares[friend_id], request_id=request_id
            )

    async def _sync_friend_shares(
        self, ctx: UserContext, expense: SharedExpense, plan: _Plan, request_id: str | None
    ) -> list[uuid.UUID]:
        """After an edit, bring the linked friends' share transactions in line with the new
        split: move those still in it, add those just added, remove those taken out.

        Returns every friend user the edit touched, for their audit events.
        """
        linked = await self._linked_users(plan.shares)
        amounts = {user_id: plan.shares[friend_id] for friend_id, user_id in linked.items()}
        had = {row.user_id: row for row in await self._share_rows(expense.id)}
        had.pop(ctx.user_id, None)  # the recorder's own share was moved by the caller
        for user_id, row in had.items():
            if user_id in amounts:
                self._transactions.change_share_row(
                    user_id, row, amount_minor=amounts[user_id], currency=expense.currency,
                    occurred_on=expense.occurred_on, description=expense.description,
                    merchant=expense.merchant, request_id=request_id,
                )  # fmt: skip
            else:
                await self._transactions.remove_share_row(user_id, row, request_id=request_id)
        for friend_id, user_id in linked.items():
            if user_id not in had:
                await self._delivery.deliver(
                    expense, user_id=user_id, amount_minor=plan.shares[friend_id],
                    request_id=request_id,
                )  # fmt: skip
        return list({*had, *amounts})

    async def _linked_users(self, shares: dict[PersonKey, int]) -> dict[uuid.UUID, uuid.UUID]:
        """Friend id to user id, for the participants who are linked to a MoneyMoney user."""
        friend_ids = [friend_id for friend_id in shares if friend_id is not None]
        rows = await self._session.execute(
            select(Friend.id, Friend.linked_user_id).where(
                Friend.id.in_(friend_ids), Friend.linked_user_id.is_not(None)
            )
        )
        return {friend_id: user_id for friend_id, user_id in rows.all() if user_id is not None}

    async def _share_rows(self, shared_expense_id: uuid.UUID) -> list[Transaction]:
        """Every participant's share transaction of this shared expense."""
        rows = await self._session.scalars(
            select(Transaction).where(Transaction.shared_expense_id == shared_expense_id)
        )
        return list(rows.all())

    @staticmethod
    def _can_see(user_id: uuid.UUID) -> Any:
        """The recorder, or a participant whose friend row for them is linked to this user."""
        taking_part = (
            select(SharedExpenseShare.shared_expense_id)
            .join(Friend, Friend.id == SharedExpenseShare.friend_id)
            .where(Friend.linked_user_id == user_id)
        )
        return or_(SharedExpense.recorder_id == user_id, SharedExpense.id.in_(taking_part))

    # -- planning: who takes part and what each owes ---------------------------------------

    async def _plan(
        self, ctx: UserContext, data: SharedExpenseWrite, *, existing: uuid.UUID | None
    ) -> _Plan:
        currency = (data.currency or ctx.base_currency).upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise ValidationFailedError(
                f"Unsupported currency: {currency}", details={"field": "currency"}
            )
        try:
            total_minor = to_minor(data.total, currency)
        except MoneyError as error:
            raise ValidationFailedError(str(error), details={"field": "total"}) from None

        people = [participant.friend_id for participant in data.participants]
        await self._check_participants(ctx, data, people, existing)
        payer: PersonKey = data.payer_friend_id
        if data.split == "equal":
            if any(participant.amount is not None for participant in data.participants):
                raise ValidationFailedError(
                    "An equal split takes no amounts.", details={"field": "split"}
                )
            shares = equal_split(total_minor, people, payer=payer)
        else:
            shares = exact_split(total_minor, self._exact_amounts(data.participants, currency))
        return _Plan(currency=currency, total_minor=total_minor, shares=shares)

    @staticmethod
    def _exact_amounts(
        participants: Sequence[ParticipantInput], currency: str
    ) -> dict[PersonKey, int]:
        amounts: dict[PersonKey, int] = {}
        for participant in participants:
            if participant.amount is None:
                raise ValidationFailedError(
                    "An exact split needs an amount for everyone.", details={"field": "split"}
                )
            try:
                amounts[participant.friend_id] = to_minor(participant.amount, currency)
            except MoneyError as error:
                raise ValidationFailedError(str(error), details={"field": "split"}) from None
        return amounts

    async def _check_participants(
        self,
        ctx: UserContext,
        data: SharedExpenseWrite,
        people: list[PersonKey],
        existing: uuid.UUID | None,
    ) -> None:
        if len(set(people)) != len(people):
            raise _participants_error("Each person can take part only once.")
        if None not in people:
            raise _participants_error("You must be one of the people sharing the expense.")
        if len(people) < 2:
            raise _participants_error("Share it with at least one friend.")
        wanted = {friend_id for friend_id in (*people, data.payer_friend_id) if friend_id}
        friends = {
            friend.id: friend
            for friend in (
                await self._session.scalars(
                    select(Friend).where(Friend.user_id == ctx.user_id, Friend.id.in_(wanted))
                )
            ).all()
        }
        if wanted - friends.keys():  # unknown, or another user's: indistinguishable on purpose
            raise NotFoundError("Friend not found")
        # Two friend rows for one linked user would give that user two shares of one bill.
        linked_users = [f.linked_user_id for f in friends.values() if f.linked_user_id]
        if len(set(linked_users)) != len(linked_users):
            raise _participants_error("Each person can take part only once.")
        already_in = await self._friends_already_in(existing) if existing else set()
        for friend in friends.values():
            if friend.is_archived and friend.id not in already_in:
                raise _participants_error(f"{friend.name} was removed from your friends.")
        payer = data.payer_friend_id
        if payer is not None:
            if payer not in people:
                raise _participants_error("The friend who paid must be one of the people sharing.")
            if len(people) != 2:
                raise _participants_error(
                    "When a friend paid, only you and that friend can share the expense."
                )

    async def _friends_already_in(self, shared_expense_id: uuid.UUID) -> set[uuid.UUID]:
        rows = await self._session.scalars(
            select(SharedExpenseShare.friend_id).where(
                SharedExpenseShare.shared_expense_id == shared_expense_id,
                SharedExpenseShare.friend_id.is_not(None),
            )
        )
        return {friend_id for friend_id in rows.all() if friend_id is not None}

    # -- helpers --------------------------------------------------------------------------

    def _add_shares(self, shared_expense_id: uuid.UUID, shares: dict[PersonKey, int]) -> None:
        for friend_id, amount_minor in shares.items():
            self._session.add(
                SharedExpenseShare(
                    id=uuid7(),
                    shared_expense_id=shared_expense_id,
                    friend_id=friend_id,
                    amount_minor=amount_minor,
                )
            )

    async def _owned(self, ctx: UserContext, shared_expense_id: uuid.UUID) -> SharedExpense:
        # Ownership is part of the WHERE clause: another user's id is simply "not found".
        expense = await self._session.scalar(
            select(SharedExpense).where(
                SharedExpense.id == shared_expense_id, SharedExpense.recorder_id == ctx.user_id
            )
        )
        if expense is None:
            raise NotFoundError("Shared expense not found")
        return expense

    async def _share_amounts(self, shared_expense_id: uuid.UUID) -> dict[PersonKey, int]:
        rows = await self._session.execute(
            select(SharedExpenseShare.friend_id, SharedExpenseShare.amount_minor).where(
                SharedExpenseShare.shared_expense_id == shared_expense_id
            )
        )
        return {friend_id: amount for friend_id, amount in rows.all()}

    @staticmethod
    def _snapshot(expense: SharedExpense, shares: dict[PersonKey, int]) -> dict[str, Any]:
        return {
            "totalMinor": expense.total_minor,
            "currency": expense.currency,
            "occurredOn": expense.occurred_on.isoformat(),
            "payerFriendId": str(expense.payer_friend_id) if expense.payer_friend_id else None,
            "shares": {str(friend_id) if friend_id else "you": amount
                       for friend_id, amount in shares.items()},
        }  # fmt: skip

    def _audit_all(
        self,
        user_ids: Sequence[uuid.UUID],
        action: str,
        entity_id: uuid.UUID,
        data: dict[str, Any],
        request_id: str | None,
    ) -> None:
        """One audit event per affected user, saved with the change itself."""
        for user_id in dict.fromkeys(user_ids):
            record_audit(
                self._session, user_id=user_id, actor="user", action=action,
                entity_type="shared_expense", entity_id=entity_id, data=data,
                request_id=request_id,
            )  # fmt: skip

    async def _bump_generations(self, user_ids: Sequence[uuid.UUID]) -> None:
        for user_id in dict.fromkeys(user_ids):
            await self._transactions.bump_generation(user_id)

    async def _views(
        self, ctx: UserContext, expenses: Sequence[SharedExpense]
    ) -> list[SharedExpenseView]:
        mine = [e for e in expenses if e.recorder_id == ctx.user_id]
        theirs = [e for e in expenses if e.recorder_id != ctx.user_id]
        views = [*await self._recorder_views(ctx, mine), *await self._friend_views(ctx, theirs)]
        by_id = {view.id: view for view in views}
        return [by_id[expense.id] for expense in expenses]

    async def _friend_views(
        self, ctx: UserContext, expenses: Sequence[SharedExpense]
    ) -> list[SharedExpenseView]:
        """The shared expenses as a linked friend sees them.

        People are named the way this user knows them (their own friend row for someone
        linked), else the way the recorder named them. Only fields of the shared expense
        itself appear: never the recorder's category, account or notes, nor the recorder's
        friend ids.
        """
        if not expenses:
            return []
        ids = [expense.id for expense in expenses]
        share_rows = (
            await self._session.execute(
                select(SharedExpenseShare, Friend)
                .outerjoin(Friend, Friend.id == SharedExpenseShare.friend_id)
                .where(SharedExpenseShare.shared_expense_id.in_(ids))
            )
        ).all()
        friends_by_id = {friend.id: friend for _, friend in share_rows if friend is not None}
        recorder_ids = {expense.recorder_id for expense in expenses}
        recorder_names = dict(
            (
                await self._session.execute(
                    select(User.id, User.display_name).where(User.id.in_(recorder_ids))
                )
            ).all()
        )
        linked_ids = {f.linked_user_id for f in friends_by_id.values() if f.linked_user_id}
        my_rows = {
            row.linked_user_id: row
            for row in (
                await self._session.scalars(
                    select(Friend).where(
                        Friend.user_id == ctx.user_id,
                        Friend.is_archived.is_(False),
                        Friend.linked_user_id.in_(recorder_ids | linked_ids),
                    )
                )
            ).all()
        }
        my_transactions = {
            expense_id: transaction_id
            for expense_id, transaction_id in (
                await self._session.execute(
                    select(Transaction.shared_expense_id, Transaction.id).where(
                        Transaction.user_id == ctx.user_id,
                        Transaction.shared_expense_id.in_(ids),
                    )
                )
            ).all()
        }

        def person(expense: SharedExpense, friend_id: uuid.UUID | None) -> PersonView:
            friend = friends_by_id.get(friend_id) if friend_id else None
            user_id = friend.linked_user_id if friend else expense.recorder_id
            if user_id == ctx.user_id:
                return PersonView(friend_id=None, name=YOU, is_you=True)
            known = my_rows.get(user_id) if user_id else None
            if known is not None:
                return PersonView(friend_id=known.id, name=known.name, is_you=False)
            name = friend.name if friend else recorder_names[expense.recorder_id]
            return PersonView(friend_id=None, name=name, is_you=False)

        views: list[SharedExpenseView] = []
        for expense in expenses:
            shares = [
                ShareView(
                    **person(expense, share.friend_id).model_dump(),
                    amount=from_minor(share.amount_minor, expense.currency),
                    amount_minor=share.amount_minor,
                    amount_formatted=format_money(share.amount_minor, expense.currency, ctx.locale),
                )
                for share, _ in share_rows
                if share.shared_expense_id == expense.id
            ]
            shares.sort(key=lambda s: (not s.is_you, s.name.lower()))
            payer = person(expense, expense.payer_friend_id)
            views.append(
                SharedExpenseView(
                    id=expense.id,
                    total=from_minor(expense.total_minor, expense.currency),
                    total_minor=expense.total_minor,
                    currency=expense.currency,
                    total_formatted=format_money(expense.total_minor, expense.currency, ctx.locale),
                    occurred_on=expense.occurred_on,
                    description=expense.description,
                    merchant=expense.merchant,
                    payer=payer,
                    paid_by_you=payer.is_you,
                    shares=shares,
                    my_transaction_id=my_transactions.get(expense.id),
                    created_at=expense.created_at,
                    updated_at=expense.updated_at,
                )
            )
        return views

    async def _recorder_views(
        self, ctx: UserContext, expenses: Sequence[SharedExpense]
    ) -> list[SharedExpenseView]:
        if not expenses:
            return []
        ids = [expense.id for expense in expenses]
        share_rows = (
            await self._session.execute(
                select(SharedExpenseShare, Friend.name)
                .outerjoin(Friend, Friend.id == SharedExpenseShare.friend_id)
                .where(SharedExpenseShare.shared_expense_id.in_(ids))
            )
        ).all()
        payer_names = {
            friend.id: friend.name
            for friend in (
                await self._session.scalars(
                    select(Friend).where(
                        Friend.id.in_({e.payer_friend_id for e in expenses if e.payer_friend_id})
                    )
                )
            ).all()
        }
        my_transactions = {
            expense_id: transaction_id
            for expense_id, transaction_id in (
                await self._session.execute(
                    select(Transaction.shared_expense_id, Transaction.id).where(
                        Transaction.user_id == ctx.user_id,
                        Transaction.shared_expense_id.in_(ids),
                    )
                )
            ).all()
        }
        shares_by_expense: dict[uuid.UUID, list[ShareView]] = {}
        for share, friend_name in share_rows:
            expense = next(e for e in expenses if e.id == share.shared_expense_id)
            shares_by_expense.setdefault(expense.id, []).append(
                ShareView(
                    friend_id=share.friend_id,
                    name=friend_name or YOU,
                    is_you=share.friend_id is None,
                    amount=from_minor(share.amount_minor, expense.currency),
                    amount_minor=share.amount_minor,
                    amount_formatted=format_money(share.amount_minor, expense.currency, ctx.locale),
                )
            )
        views: list[SharedExpenseView] = []
        for expense in expenses:
            payer = (
                PersonView(friend_id=None, name=YOU, is_you=True)
                if expense.payer_friend_id is None
                else PersonView(
                    friend_id=expense.payer_friend_id,
                    name=payer_names[expense.payer_friend_id],
                    is_you=False,
                )
            )
            # You first, then friends by name, so the card reads the same every time.
            shares = sorted(
                shares_by_expense.get(expense.id, []), key=lambda s: (not s.is_you, s.name.lower())
            )
            views.append(
                SharedExpenseView(
                    id=expense.id,
                    total=from_minor(expense.total_minor, expense.currency),
                    total_minor=expense.total_minor,
                    currency=expense.currency,
                    total_formatted=format_money(expense.total_minor, expense.currency, ctx.locale),
                    occurred_on=expense.occurred_on,
                    description=expense.description,
                    merchant=expense.merchant,
                    payer=payer,
                    paid_by_you=payer.is_you,
                    shares=shares,
                    my_transaction_id=my_transactions.get(expense.id),
                    created_at=expense.created_at,
                    updated_at=expense.updated_at,
                )
            )
        return views


def _users_of(ctx: UserContext, rows: Sequence[Transaction]) -> list[uuid.UUID]:
    """The recorder first, then everyone else who holds a share transaction."""
    return [ctx.user_id, *(row.user_id for row in rows if row.user_id != ctx.user_id)]


class _Plan:
    """The checked outcome of a request: the currency, the total and what each person owes."""

    def __init__(self, *, currency: str, total_minor: int, shares: dict[PersonKey, int]) -> None:
        self.currency = currency
        self.total_minor = total_minor
        self.shares = shares


__all__ = ["SharedExpenseService"]
