"""A chat preview is bounded while its source overview remains complete."""

from datetime import UTC, date, datetime

import pytest

from finance_core.llm.schemas import ReportSpec
from finance_core.reports.schemas import CategoryTotal, MerchantTotal, ReportOverview, TrendBucket
from finance_core.workflows.reporting import report_interaction
from tests.unit.test_report_insights import PERIOD, report


def overview() -> ReportOverview:
    data = report()
    amount = data.expense.current
    data.expense_by_category = [
        CategoryTotal(
            category_id=None,
            slug=str(i),
            name=str(i),
            icon=None,
            total=amount,
            count=1,
            share_percent=10,
        )
        for i in range(10)
    ]
    data.top_merchants = [
        MerchantTotal(key=str(i), name=str(i), total=amount, count=1) for i in range(11)
    ]
    data.trend = [
        TrendBucket(
            start=date(2026, 10, 1),
            end=date(2026, 10, 1),
            label=str(i),
            income=amount,
            expense=amount,
            net=amount,
        )
        for i in range(121)
    ]
    return ReportOverview(
        period=PERIOD,
        comparison_period=PERIOD,
        bucket_kind="day",
        base_currency="INR",
        currencies=[data],
        transaction_count=100,
        generated_at=datetime(2026, 10, 24, tzinfo=UTC),
    )


def test_preview_bounds_do_not_mutate_full_report_or_its_exact_metrics() -> None:
    source = overview()
    card = report_interaction(source, ReportSpec(kind="breakdown"), "report")
    assert card.preview is not None
    assert len(card.preview.expense_by_category) == 5
    assert len(card.preview.top_merchants) == 3
    assert card.preview.trend == []
    assert len(source.currencies[0].expense_by_category) == 10
    assert len(source.currencies[0].top_merchants) == 11
    trend = report_interaction(source, ReportSpec(kind="trend"), "trend")
    assert trend.preview is not None
    assert len(trend.preview.trend) == 120
    assert len(source.currencies[0].trend) == 121
    assert trend.preview.expense == source.currencies[0].expense
    assert card.generated_at == source.generated_at


def test_missing_currency_has_no_converted_or_combined_money() -> None:
    card = report_interaction(overview(), ReportSpec(currency="USD"), "report")
    assert card.currency == "USD" and card.preview is None
    assert card.available_currencies == ["INR"]
    assert "currency=USD" in card.report_href
    with pytest.raises(ValueError, match="supported ISO"):
        report_interaction(overview(), ReportSpec(currency="XYZ"), "report")
