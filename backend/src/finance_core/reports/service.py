"""Deterministic financial aggregation with a generation-keyed cache."""

from __future__ import annotations

import logging
import random
import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.cache.primitives import UserDataGeneration
from finance_core.cache.redis import RedisClient, RedisUnavailableError
from finance_core.categories.models import Category
from finance_core.clock import Clock
from finance_core.dates import DateRange
from finance_core.reports.schemas import CategoryTotal, CurrencySummary, PeriodView, SpendingSummary
from finance_core.schemas import MoneyAmount
from finance_core.transactions.models import Transaction
from finance_core.users.context import UserContext

logger = logging.getLogger(__name__)

_CACHE_VERSION = "v1"  # bump when the SpendingSummary shape changes


@dataclass
class _Bucket:
    total: int = 0
    count: int = 0
    by_category: dict[uuid.UUID | None, tuple[int, int]] = field(default_factory=dict)


class ReportService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock,
        redis: RedisClient | None = None,
        generation: UserDataGeneration | None = None,
        cache_ttl_seconds: int = 600,
    ) -> None:
        self._session = session
        self._clock = clock
        self._redis = redis
        self._generation = generation
        self._ttl = cache_ttl_seconds

    async def summary(self, ctx: UserContext, period: DateRange) -> SpendingSummary:
        cache_key: str | None = None
        if self._redis is not None and self._generation is not None:
            try:
                generation = await self._generation.current(ctx.user_id)
                cache_key = self._redis.key(
                    "summary", _CACHE_VERSION, ctx.user_id, generation,
                    period.start.isoformat(), period.end.isoformat(),
                    ctx.base_currency, ctx.locale,
                )  # fmt: skip
                cached = await self._redis.get(cache_key)
                if cached is not None:
                    return SpendingSummary.model_validate_json(cached)
            except RedisUnavailableError:
                cache_key = None  # degrade to the database

        summary = await self._compute(ctx, period)
        if cache_key is not None and self._redis is not None:
            # Jittered TTL so entries written together do not all expire together.
            ttl = self._ttl + random.randint(0, max(1, self._ttl // 10))  # noqa: S311
            try:
                await self._redis.set(cache_key, summary.model_dump_json(), ttl_seconds=ttl)
            except RedisUnavailableError:
                pass
        return summary

    async def _compute(self, ctx: UserContext, period: DateRange) -> SpendingSummary:
        rows = (
            await self._session.execute(
                select(
                    Transaction.currency,
                    Transaction.type,
                    Transaction.category_id,
                    func.count(),
                    func.sum(Transaction.amount_minor),
                )
                .where(
                    Transaction.user_id == ctx.user_id,
                    Transaction.deleted_at.is_(None),
                    Transaction.type.in_(("expense", "income")),
                    Transaction.occurred_on >= period.start,
                    Transaction.occurred_on <= period.end,
                )
                .group_by(Transaction.currency, Transaction.type, Transaction.category_id)
            )
        ).all()

        buckets: dict[str, dict[str, _Bucket]] = defaultdict(
            lambda: {"expense": _Bucket(), "income": _Bucket()}
        )
        category_ids: set[uuid.UUID] = set()
        transaction_count = 0
        for currency, tx_type, category_id, count, total in rows:
            bucket = buckets[currency][tx_type]
            bucket.total += int(total)
            bucket.count += int(count)
            bucket.by_category[category_id] = (int(total), int(count))
            transaction_count += int(count)
            if category_id is not None:
                category_ids.add(category_id)

        categories: dict[uuid.UUID, Category] = {}
        if category_ids:
            result = await self._session.scalars(select(Category).where(Category.id.in_(category_ids)))
            categories = {c.id: c for c in result.all()}

        def breakdown(bucket: _Bucket, currency: str) -> list[CategoryTotal]:
            items: list[CategoryTotal] = []
            for category_id, (total, count) in bucket.by_category.items():
                category = categories.get(category_id) if category_id else None
                share = round(total * 100 / bucket.total, 1) if bucket.total else 0.0
                items.append(
                    CategoryTotal(
                        category_id=category_id,
                        slug=category.slug if category else "uncategorized",
                        name=category.name if category else "Uncategorized",
                        icon=category.icon if category else "circle-help",
                        total=MoneyAmount.of(total, currency, ctx.locale),
                        count=count,
                        share_percent=share,
                    )
                )
            items.sort(key=lambda item: (-item.total.amount_minor, item.name))
            return items

        summaries = [
            CurrencySummary(
                currency=currency,
                income=MoneyAmount.of(kinds["income"].total, currency, ctx.locale),
                expense=MoneyAmount.of(kinds["expense"].total, currency, ctx.locale),
                net=MoneyAmount.of(
                    kinds["income"].total - kinds["expense"].total, currency, ctx.locale
                ),
                income_count=kinds["income"].count,
                expense_count=kinds["expense"].count,
                expense_by_category=breakdown(kinds["expense"], currency),
                income_by_category=breakdown(kinds["income"], currency),
            )
            for currency, kinds in buckets.items()
        ]
        summaries.sort(key=lambda s: (s.currency != ctx.base_currency, -s.expense.amount_minor))
        return SpendingSummary(
            period=PeriodView(start=period.start, end=period.end, label=period.label),
            base_currency=ctx.base_currency,
            currencies=summaries,
            transaction_count=transaction_count,
            generated_at=self._clock.now(),
        )
