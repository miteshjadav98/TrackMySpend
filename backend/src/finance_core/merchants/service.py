"""Merchant rules: learn which category a user files each merchant under, and look it up.

The transaction service calls `learn` for every save, inside the save's own database
transaction, so a rule is written together with the transaction that taught it or not at
all. The chat workflow calls `category_for` to file a merchant's next transaction.
Settings lists rules with `search`, and the user changes or forgets one with
`change_category` and `forget`.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.categories.defaults import FALLBACK_SLUGS
from finance_core.categories.models import Category
from finance_core.categories.schemas import CategoryRef
from finance_core.categories.service import CategoryService
from finance_core.clock import Clock
from finance_core.errors import NotFoundError, ValidationFailedError
from finance_core.ids import uuid7
from finance_core.merchants.keys import merchant_key
from finance_core.merchants.models import MerchantRule
from finance_core.merchants.schemas import MerchantRulePage, MerchantRuleQuery, MerchantRuleView

MAX_PAGE_SIZE = 100


def to_view(rule: MerchantRule, category: Category) -> MerchantRuleView:
    return MerchantRuleView(
        id=rule.id,
        merchant=rule.merchant,
        type=rule.type,
        category=CategoryRef(
            id=category.id, slug=category.slug, name=category.name, icon=category.icon
        ),
        times_used=rule.times_used,
        last_used_at=rule.last_used_at,
    )


def _audit_snapshot(rule: MerchantRule) -> dict[str, Any]:
    return {"merchant": rule.merchant, "type": rule.type, "categoryId": str(rule.category_id)}


def _encode_cursor(rule: MerchantRule) -> str:
    """Where the next page starts: just after this rule, in last-used order."""
    raw = json.dumps({"t": rule.last_used_at.isoformat(), "i": str(rule.id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(data["t"]), uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ValidationFailedError(
            "Invalid pagination cursor", details={"field": "cursor"}
        ) from None


class MerchantRuleService:
    """Learns, looks up, changes and forgets merchant rules, always scoped by user.

    `learn` never commits: the save that teaches a rule owns the database transaction.
    `change_category` and `forget` are the user's own edits, so each commits itself, together
    with its audit event.
    """

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

    # -- Settings: list, change and forget ------------------------------------------------

    async def search(self, user_id: uuid.UUID, query: MerchantRuleQuery) -> MerchantRulePage:
        """This user's rules, most recently used first, one page at a time."""
        limit = max(1, min(query.limit, MAX_PAGE_SIZE))
        stmt = (
            select(MerchantRule, Category)
            .join(Category, Category.id == MerchantRule.category_id)
            .where(MerchantRule.user_id == user_id)
            .order_by(MerchantRule.last_used_at.desc(), MerchantRule.id.desc())
        )
        if query.type:
            stmt = stmt.where(MerchantRule.type == query.type)
        # Searched by key, the way merchants are matched: "SWIGGY!" finds Swiggy.
        searched_key = merchant_key(query.merchant or "")
        if searched_key:
            stmt = stmt.where(MerchantRule.merchant_key.contains(searched_key, autoescape=True))
        if query.cursor:
            last_used_at, rule_id = _decode_cursor(query.cursor)
            stmt = stmt.where(
                tuple_(MerchantRule.last_used_at, MerchantRule.id) < tuple_(last_used_at, rule_id)
            )
        # One row more than the page holds tells us whether another page follows.
        rows = (await self._session.execute(stmt.limit(limit + 1))).all()
        page, has_more = rows[:limit], len(rows) > limit
        return MerchantRulePage(
            items=[to_view(rule, category) for rule, category in page],
            next_cursor=_encode_cursor(page[-1][0]) if has_more else None,
        )

    async def change_category(
        self,
        user_id: uuid.UUID,
        rule_id: uuid.UUID,
        category_id: uuid.UUID,
        *,
        request_id: str | None = None,
    ) -> MerchantRuleView:
        """File this rule's merchant under another category, of the same type, from now on."""
        rule = await self._own_rule(user_id, rule_id)
        category = await CategoryService(self._session).get_visible(user_id, category_id)
        if category.kind != rule.type:
            raise ValidationFailedError(
                f"'{category.name}' is an {category.kind} category.",
                details={"field": "categoryId"},
            )
        if category.slug in FALLBACK_SLUGS:
            # The same reason learning skips them: "I don't know" never becomes a rule.
            raise ValidationFailedError(
                f"A rule can't file into '{category.name}'. Forget the rule instead.",
                details={"field": "categoryId"},
            )
        record_audit(
            self._session, user_id=user_id, actor="user", action="merchant_rule.changed",
            entity_type="merchant_rule", entity_id=rule.id,
            data={**_audit_snapshot(rule), "categoryId": [str(rule.category_id), str(category.id)]},
            request_id=request_id,
        )  # fmt: skip
        rule.category_id = category.id
        await self._session.commit()
        return to_view(rule, category)

    async def forget(
        self, user_id: uuid.UUID, rule_id: uuid.UUID, *, request_id: str | None = None
    ) -> None:
        """Delete the rule. Learning stays on: the merchant's next save teaches a new one."""
        rule = await self._own_rule(user_id, rule_id)
        record_audit(
            self._session, user_id=user_id, actor="user", action="merchant_rule.forgotten",
            entity_type="merchant_rule", entity_id=rule.id, data=_audit_snapshot(rule),
            request_id=request_id,
        )  # fmt: skip
        await self._session.delete(rule)
        await self._session.commit()

    async def _own_rule(self, user_id: uuid.UUID, rule_id: uuid.UUID) -> MerchantRule:
        # Ownership is part of the WHERE clause: another user's rule is simply "not found".
        rule = await self._session.scalar(
            select(MerchantRule).where(MerchantRule.id == rule_id, MerchantRule.user_id == user_id)
        )
        if rule is None:
            raise NotFoundError("Merchant rule not found")
        return rule
