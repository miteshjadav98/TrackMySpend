"""Merchant rules: learn which category a user files each merchant under, and look it up.

The transaction service calls `learn` for every save, inside the save's own database
transaction, so a rule is written together with the transaction that taught it or not at
all. The chat workflow calls `category_for` to file a merchant's next transaction.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.categories.defaults import FALLBACK_SLUGS
from finance_core.categories.models import Category
from finance_core.clock import Clock
from finance_core.ids import uuid7
from finance_core.merchants.keys import merchant_key
from finance_core.merchants.models import MerchantRule


class MerchantRuleService:
    """Learns and looks up merchant rules, always scoped by user. Never commits: the caller
    owns the database transaction."""

    def __init__(self, session: AsyncSession, *, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    async def learn(
        self,
        user_id: uuid.UUID,
        *,
        type: str,
        merchant: str | None,
        category_id: uuid.UUID | None,
    ) -> None:
        """Remember `category_id` as the category for this merchant and type, and count the use.

        Nothing is learned without a merchant or a category (a transfer has no category),
        or from a fallback category: "I don't know" never becomes a rule.
        """
        key = merchant_key(merchant or "")
        if not key or category_id is None:
            return
        category = await self._session.get(Category, category_id)
        if category is None or category.slug in FALLBACK_SLUGS:
            return
        new_rule = pg_insert(MerchantRule).values(
            id=uuid7(),
            user_id=user_id,
            type=type,
            merchant_key=key,
            merchant=merchant,
            category_id=category_id,
            times_used=1,
            last_used_at=self._clock.now(),
        )
        await self._session.execute(
            new_rule.on_conflict_do_update(
                index_elements=["user_id", "type", "merchant_key"],
                set_={
                    "merchant": new_rule.excluded.merchant,
                    "category_id": new_rule.excluded.category_id,
                    "times_used": MerchantRule.times_used + 1,
                    "last_used_at": new_rule.excluded.last_used_at,
                    "updated_at": func.now(),  # ON CONFLICT skips the model's onupdate
                },
            )
        )

    async def find(
        self, user_id: uuid.UUID, *, type: str, merchant: str | None
    ) -> MerchantRule | None:
        """This user's rule for the merchant and type, or None."""
        key = merchant_key(merchant or "")
        if not key:
            return None
        return await self._session.scalar(
            select(MerchantRule).where(
                MerchantRule.user_id == user_id,
                MerchantRule.type == type,
                MerchantRule.merchant_key == key,
            )
        )

    async def category_for(
        self, user_id: uuid.UUID, *, type: str, merchant: str | None
    ) -> Category | None:
        """The category this user files the merchant under, or None if there is no rule.

        A rule whose category has been archived is ignored.
        """
        rule = await self.find(user_id, type=type, merchant=merchant)
        if rule is None:
            return None
        category = await self._session.get(Category, rule.category_id)
        return category if category is not None and not category.is_archived else None
