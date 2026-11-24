from __future__ import annotations

import uuid
from datetime import date, datetime

from finance_core.schemas import ApiModel, MoneyAmount


class PeriodView(ApiModel):
    start: date
    end: date
    label: str


class CategoryTotal(ApiModel):
    category_id: uuid.UUID | None
    slug: str
    name: str
    icon: str | None
    total: MoneyAmount
    count: int
    share_percent: float  # presentation only; totals themselves are exact


class CurrencySummary(ApiModel):
    currency: str
    income: MoneyAmount
    expense: MoneyAmount
    net: MoneyAmount  # income - expense; may be negative
    income_count: int
    expense_count: int
    expense_by_category: list[CategoryTotal]
    income_by_category: list[CategoryTotal]


class SpendingSummary(ApiModel):
    """Totals for one period, computed in SQL from the ledger (never by the model).

    Amounts are grouped per currency: values in different currencies are never summed.
    """

    period: PeriodView
    base_currency: str
    currencies: list[CurrencySummary]
    transaction_count: int
    generated_at: datetime
    data_source: str = "Transactions recorded in MoneyMoney"


class MetricComparison(ApiModel):
    """One exact monetary metric and its equal-length previous-period comparison."""

    current: MoneyAmount
    previous: MoneyAmount
    change: MoneyAmount
    change_percent: float | None


class TrendBucket(ApiModel):
    start: date
    end: date
    label: str
    income: MoneyAmount
    expense: MoneyAmount
    net: MoneyAmount


class MerchantTotal(ApiModel):
    key: str
    name: str
    total: MoneyAmount
    count: int
    is_other: bool = False


class CurrencyReport(ApiModel):
    currency: str
    income: MetricComparison
    expense: MetricComparison
    net: MetricComparison
    expense_by_category: list[CategoryTotal]
    top_merchants: list[MerchantTotal]
    trend: list[TrendBucket]


class ReportOverview(ApiModel):
    """A deterministic chart/report read model; monetary values never cross currencies."""

    period: PeriodView
    comparison_period: PeriodView
    bucket_kind: str
    base_currency: str
    currencies: list[CurrencyReport]
    transaction_count: int
    generated_at: datetime
    data_source: str = "Transactions recorded in MoneyMoney"
