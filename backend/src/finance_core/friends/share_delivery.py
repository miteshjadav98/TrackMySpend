"""Share delivery: puts a shared expense into a linked friend's own records.

A friend who is a MoneyMoney user gets their share as an ordinary expense transaction (ADR
0001), so their summaries need no special case. This module decides what that transaction
looks like for them and brings past shared expenses over when two users link later.

The friend's category is chosen in this order:
1. their own merchant rule for the merchant,
2. their category with the same slug as the recorder's, when the recorder used a built-in one,
3. their built-in "Other".
The recorder's account and notes are never copied. The share does not teach the friend's
merchant rules; only a category change the friend makes themselves does.

Nothing here commits: the caller owns the database transaction.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.categories.models import Category
from finance_core.categories.service import CategoryService
from finance_core.clock import Clock
from finance_core.friends.models import Friend, SharedExpense, SharedExpenseShare
from finance_core.merchants.service import MerchantRuleService
from finance_core.transactions.models import Transaction
from finance_core.transactions.schemas import NewTransaction
from finance_core.transactions.service import TransactionService

FALLBACK_SLUG = "other"


class ShareDelivery:
    """Creates the share transactions linked friends get, once each."""

    def __init__(self, session: AsyncSession, *, clock: Clock) -> None:
        self._session = session
        self._transactions = TransactionService(session, clock=clock)
        self._categories = CategoryService(session)
        self._merchant_rules = MerchantRuleService(session, clock=clock)

    async def deliver(
        self,
        expense: SharedExpense,
        *,
        user_id: uuid.UUID,
        amount_minor: int,
        request_id: str | None = None,
    ) -> bool:
        """Give the user their share of the expense. Returns False if they already have it."""
        already = await self._session.scalar(
            select(Transaction.id).where(
                Transaction.user_id == user_id, Transaction.shared_expense_id == expense.id
            )
        )
        if already is not None:
            return False  # a retry (or a second invite) must never duplicate the share
        share = NewTransaction(
            type="expense",
            amount_minor=amount_minor,
            currency=expense.currency,
            occurred_on=expense.occurred_on,
            category_id=await self._category_for(expense, user_id),
            description=expense.description,
            merchant=expense.merchant,
            payment_method=None,
        )
        await self._transactions.add_share_row(
            user_id,
            share,
            shared_expense_id=expense.id,
            learn_merchant=False,
            request_id=request_id,
        )
        return True

    async def bring_over_between(
        self, first_user_id: uuid.UUID, second_user_id: uuid.UUID, request_id: str | None = None
    ) -> None:
        """After two users link, give each the shared expenses the other recorded with them.

        Settlements need nothing here: they are not transactions, and each side already
        reads them through the link.
        """
        for recorder_id, friend_user_id in (
            (first_user_id, second_user_id),
            (second_user_id, first_user_id),
        ):
            rows = await self._session.execute(
                select(SharedExpense, SharedExpenseShare.amount_minor)
                .join(SharedExpenseShare, SharedExpenseShare.shared_expense_id == SharedExpense.id)
                .join(Friend, Friend.id == SharedExpenseShare.friend_id)
                .where(
                    SharedExpense.recorder_id == recorder_id,
                    Friend.linked_user_id == friend_user_id,
                )
                .order_by(SharedExpense.occurred_on, SharedExpense.id)
            )
            for expense, amount_minor in rows.all():
                delivered = await self.deliver(
                    expense,
                    user_id=friend_user_id,
                    amount_minor=amount_minor,
                    request_id=request_id,
                )
                if delivered:
                    record_audit(
                        self._session, user_id=friend_user_id, actor="user",
                        action="shared_expense.linked", entity_type="shared_expense",
                        entity_id=expense.id, data={"recordedBy": str(recorder_id)},
                        request_id=request_id,
                    )  # fmt: skip

    async def _category_for(self, expense: SharedExpense, user_id: uuid.UUID) -> uuid.UUID | None:
        by_rule = await self._merchant_rules.category_for(
            user_id, type="expense", merchant=expense.merchant
        )
        if by_rule is not None:
            return by_rule.id
        slugs = [FALLBACK_SLUG]
        recorders_slug = await self._recorders_builtin_slug(expense)
        if recorders_slug is not None:
            slugs.insert(0, recorders_slug)
        for slug in slugs:
            category = await self._categories.by_slug(user_id, slug, "expense")
            if category is not None:
                return category.id
        return None

    async def _recorders_builtin_slug(self, expense: SharedExpense) -> str | None:
        """The slug of the recorder's category, only when it is a built-in one: a category the
        recorder made up means nothing to the friend."""
        return await self._session.scalar(
            select(Category.slug)
            .join(Transaction, Transaction.category_id == Category.id)
            .where(
                Transaction.user_id == expense.recorder_id,
                Transaction.shared_expense_id == expense.id,
                Category.user_id.is_(None),
            )
        )


__all__ = ["ShareDelivery"]
