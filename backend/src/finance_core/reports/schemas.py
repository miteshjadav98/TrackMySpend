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
