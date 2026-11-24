"""Deterministic financial aggregation with a generation-keyed cache."""

from __future__ import annotations

import calendar
import contextlib
import logging
import random
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from finance_core.cache.primitives import UserDataGeneration
from finance_core.cache.redis import RedisClient, RedisUnavailableError
from finance_core.categories.models import Category
from finance_core.clock import Clock
from finance_core.dates import DateRange, preceding_period
from finance_core.merchants.report_groups import report_merchant_groups
from finance_core.reports.schemas import (
    CategoryTotal,
    CurrencyReport,
    CurrencySummary,
    MerchantTotal,
    MetricComparison,
    PeriodView,
    ReportOverview,
    SpendingSummary,
    TrendBucket,
)
from finance_core.schemas import MoneyAmount
from finance_core.transactions.models import Transaction
from finance_core.users.context import UserContext

logger = logging.getLogger(__name__)

_CACHE_VERSION = "v1"  # bump when the SpendingSummary shape changes
_OVERVIEW_CACHE_VERSION = "v1"


@dataclass
class _Bucket:
    total: int = 0
    count: int = 0
    by_category: dict[uuid.UUID | None, tuple[int, int]] = field(default_factory=dict)


def trend_ranges(period: DateRange) -> tuple[str, list[DateRange]]:
    """Choose bounded deterministic buckets and cover every day in the requested period."""

    if period.days <= 62:
        return (
            "day",
            [
                DateRange(day, day, f"{day.day} {calendar.month_abbr[day.month]}")
                for offset in range(period.days)
                for day in [period.start + timedelta(days=offset)]
            ],
        )
    if period.days <= 366:
        ranges: list[DateRange] = []
        start = period.start
        while start <= period.end:
            end = min(start + timedelta(days=6), period.end)
            ranges.append(
                DateRange(
                    start,
                    end,
                    f"{start.day} {calendar.month_abbr[start.month]}-"
                    f"{end.day} {calendar.month_abbr[end.month]}",
                )
            )
            start = end + timedelta(days=1)
        return "week", ranges

    ranges = []
    cursor = date(period.start.year, period.start.month, 1)
    while cursor <= period.end:
        last = date(cursor.year, cursor.month, calendar.monthrange(cursor.year, cursor.month)[1])
        start, end = max(cursor, period.start), min(last, period.end)
        ranges.append(DateRange(start, end, f"{calendar.month_abbr[cursor.month]} {cursor.year}"))
        cursor = date(cursor.year + (cursor.month == 12), cursor.month % 12 + 1, 1)
    return "month", ranges


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
            with contextlib.suppress(RedisUnavailableError):
                await self._redis.set(cache_key, summary.model_dump_json(), ttl_seconds=ttl)
        return summary

    async def overview(self, ctx: UserContext, period: DateRange) -> ReportOverview:
        """Chart-ready exact aggregates for one period and its equal-length predecessor."""

        started = time.perf_counter()
        comparison = preceding_period(period)
        cache_key: str | None = None
        if self._redis is not None and self._generation is not None:
            try:
                generation = await self._generation.current(ctx.user_id)
                cache_key = self._redis.key(
                    "report-overview",
                    _OVERVIEW_CACHE_VERSION,
                    ctx.user_id,
                    generation,
                    period.start.isoformat(),
                    period.end.isoformat(),
                    ctx.base_currency,
                    ctx.locale,
                )
                cached = await self._redis.get(cache_key)
                if cached is not None:
                    overview = ReportOverview.model_validate_json(cached)
                    self._log_overview(overview, period, cache_hit=True, started=started)
                    return overview
            except RedisUnavailableError:
                cache_key = None

        overview = await self._compute_overview(ctx, period, comparison)
        if cache_key is not None and self._redis is not None:
            ttl = self._ttl + random.randint(0, max(1, self._ttl // 10))  # noqa: S311
            with contextlib.suppress(RedisUnavailableError):
                await self._redis.set(cache_key, overview.model_dump_json(), ttl_seconds=ttl)
        self._log_overview(overview, period, cache_hit=False, started=started)
        return overview

    @staticmethod
    def _log_overview(
        overview: ReportOverview,
        period: DateRange,
        *,
        cache_hit: bool,
        started: float,
    ) -> None:
        logger.info(
            "report overview generated",
            extra={
                "reportKind": "overview",
                "rangeDays": period.days,
                "currencyCount": len(overview.currencies),
                "bucketCount": sum(len(item.trend) for item in overview.currencies),
                "cacheHit": cache_hit,
                "durationMs": round((time.perf_counter() - started) * 1000, 1),
            },
        )

    async def _compute_overview(
        self, ctx: UserContext, period: DateRange, comparison: DateRange
    ) -> ReportOverview:
        current_rows = (
            await self._session.execute(
                select(
                    Transaction.currency,
                    Transaction.type,
                    Transaction.category_id,
                    func.count(),
                    func.sum(Transaction.amount_minor),
                )
                .where(*self._report_filters(ctx, period))
                .group_by(Transaction.currency, Transaction.type, Transaction.category_id)
            )
        ).all()
        previous_rows = (
            await self._session.execute(
                select(
                    Transaction.currency,
                    Transaction.type,
                    func.sum(Transaction.amount_minor),
                )
                .where(*self._report_filters(ctx, comparison))
                .group_by(Transaction.currency, Transaction.type)
            )
        ).all()
        trend_rows = (
            await self._session.execute(
                select(
                    Transaction.currency,
                    Transaction.type,
                    Transaction.occurred_on,
                    func.sum(Transaction.amount_minor),
                )
                .where(*self._report_filters(ctx, period))
                .group_by(Transaction.currency, Transaction.type, Transaction.occurred_on)
            )
        ).all()
        merchant_rows = (
            await self._session.execute(
                select(
                    Transaction.currency,
                    Transaction.merchant,
                    func.count(),
                    func.sum(Transaction.amount_minor),
                )
                .where(*self._report_filters(ctx, period), Transaction.type == "expense")
                .group_by(Transaction.currency, Transaction.merchant)
            )
        ).all()

        current: dict[str, dict[str, _Bucket]] = defaultdict(
            lambda: {"expense": _Bucket(), "income": _Bucket()}
        )
        category_ids: set[uuid.UUID] = set()
        transaction_count = 0
        for currency, tx_type, category_id, count, total in current_rows:
            bucket = current[currency][tx_type]
            bucket.total += int(total)
            bucket.count += int(count)
            bucket.by_category[category_id] = (int(total), int(count))
            transaction_count += int(count)
            if category_id is not None:
                category_ids.add(category_id)

        categories: dict[uuid.UUID, Category] = {}
        if category_ids:
            result = await self._session.scalars(
                select(Category).where(Category.id.in_(category_ids))
            )
            categories = {category.id: category for category in result.all()}

        previous: dict[str, dict[str, int]] = defaultdict(lambda: {"expense": 0, "income": 0})
        for currency, tx_type, total in previous_rows:
            previous[currency][tx_type] = int(total)

        kind, ranges = trend_ranges(period)
        day_to_bucket = {
            day: index
            for index, item in enumerate(ranges)
            for offset in range(item.days)
            for day in [item.start + timedelta(days=offset)]
        }
        trend_values: dict[str, list[dict[str, int]]] = defaultdict(
            lambda: [{"expense": 0, "income": 0} for _ in ranges]
        )
        for currency, tx_type, occurred_on, total in trend_rows:
            trend_values[currency][day_to_bucket[occurred_on]][tx_type] += int(total)

        merchants: dict[str, list[tuple[str | None, int, int]]] = defaultdict(list)
        for currency, merchant, count, total in merchant_rows:
            merchants[currency].append((merchant, int(total), int(count)))

        reports = [
            self._currency_report(
                ctx,
                currency,
                kinds,
                previous[currency],
                categories,
                ranges,
                trend_values[currency],
                merchants[currency],
            )
            for currency, kinds in current.items()
        ]
        reports.sort(
            key=lambda item: (
                item.currency != ctx.base_currency,
                -item.expense.current.amount_minor,
                item.currency,
            )
        )
        return ReportOverview(
            period=PeriodView(start=period.start, end=period.end, label=period.label),
            comparison_period=PeriodView(
                start=comparison.start, end=comparison.end, label=comparison.label
            ),
            bucket_kind=kind,
            base_currency=ctx.base_currency,
            currencies=reports,
            transaction_count=transaction_count,
            generated_at=self._clock.now(),
        )

    @staticmethod
    def _report_filters(ctx: UserContext, period: DateRange) -> tuple[ColumnElement[bool], ...]:
        return (
            Transaction.user_id == ctx.user_id,
            Transaction.deleted_at.is_(None),
            Transaction.type.in_(("expense", "income")),
            Transaction.occurred_on >= period.start,
            Transaction.occurred_on <= period.end,
        )

    def _currency_report(
        self,
        ctx: UserContext,
        currency: str,
        current: dict[str, _Bucket],
        previous: dict[str, int],
        categories: dict[uuid.UUID, Category],
        ranges: list[DateRange],
        trend_values: list[dict[str, int]],
        merchant_rows: list[tuple[str | None, int, int]],
    ) -> CurrencyReport:
        expense = current["expense"].total
        income = current["income"].total
        previous_expense = previous["expense"]
        previous_income = previous["income"]

        category_totals: list[CategoryTotal] = []
        for category_id, (total, count) in current["expense"].by_category.items():
            category = categories.get(category_id) if category_id else None
            category_totals.append(
                CategoryTotal(
                    category_id=category_id,
                    slug=category.slug if category else "uncategorized",
                    name=category.name if category else "Uncategorized",
                    icon=category.icon if category else "circle-help",
                    total=MoneyAmount.of(total, currency, ctx.locale),
                    count=count,
                    share_percent=round(total * 100 / expense, 1) if expense else 0.0,
                )
            )
        category_totals.sort(key=lambda item: (-item.total.amount_minor, item.name))

        trend = [
            TrendBucket(
                start=item.start,
                end=item.end,
                label=item.label,
                income=MoneyAmount.of(values["income"], currency, ctx.locale),
                expense=MoneyAmount.of(values["expense"], currency, ctx.locale),
                net=MoneyAmount.of(values["income"] - values["expense"], currency, ctx.locale),
            )
            for item, values in zip(ranges, trend_values, strict=True)
        ]
        return CurrencyReport(
            currency=currency,
            income=self._metric(income, previous_income, currency, ctx.locale),
            expense=self._metric(expense, previous_expense, currency, ctx.locale),
            net=self._metric(
                income - expense,
                previous_income - previous_expense,
                currency,
                ctx.locale,
            ),
            expense_by_category=category_totals,
            top_merchants=self._merchant_totals(merchant_rows, currency, ctx.locale),
            trend=trend,
        )

    @staticmethod
    def _metric(current: int, previous: int, currency: str, locale: str) -> MetricComparison:
        change = current - previous
        percent = round(change * 100 / abs(previous), 1) if previous else None
        return MetricComparison(
            current=MoneyAmount.of(current, currency, locale),
            previous=MoneyAmount.of(previous, currency, locale),
            change=MoneyAmount.of(change, currency, locale),
            change_percent=percent,
        )

    @staticmethod
    def _merchant_totals(
        rows: list[tuple[str | None, int, int]], currency: str, locale: str
    ) -> list[MerchantTotal]:
        return [
            MerchantTotal(
                key=group.key,
                name=group.name,
                total=MoneyAmount.of(group.total, currency, locale),
                count=group.count,
                is_other=group.is_other,
            )
            for group in report_merchant_groups(rows)
        ]

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
            result = await self._session.scalars(
                select(Category).where(Category.id.in_(category_ids))
            )
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
