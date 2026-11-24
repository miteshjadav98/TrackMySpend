"""Insight evidence follows exact totals, handles ties and never ranks the remainder as a merchant."""

from datetime import date

from finance_core.reports.insights import build_insights
from finance_core.reports.schemas import CategoryTotal, CurrencyReport, MerchantTotal, PeriodView
from finance_core.reports.service import ReportService
from finance_core.schemas import MoneyAmount


def report(current: int = 100, previous: int = 0) -> CurrencyReport:
    metric = ReportService._metric(current, previous, "INR", "en-IN")
    return CurrencyReport(
        currency="INR",
        income=metric,
        expense=metric,
        net=metric,
        expense_by_category=[],
        top_merchants=[],
        trend=[],
    )


PERIOD = PeriodView(start=date(2026, 10, 1), end=date(2026, 10, 24), label="October")


def test_change_preserves_evidence_and_explicit_zero_previous_spending() -> None:
    data = report()
    [fact] = build_insights(data, PERIOD, "en-IN")
    assert fact.current == data.expense.current
    assert fact.previous == data.expense.previous
    assert fact.change_percent is None
    assert "no previous spending" in fact.text
    assert "INR" in fact.text and "2026" in fact.text
    assert "unchanged" in build_insights(report(100, 100), PERIOD, "en-IN")[0].text
    assert build_insights(report(0, 0), PERIOD, "en-IN") == []
    declining = build_insights(report(0, 100), PERIOD, "en-IN")[0]
    assert declining.change_percent == -100
    assert declining.current.amount_minor == 0


def test_ties_are_explicit_and_other_merchants_is_not_a_single_merchant() -> None:
    data = report()
    amount = MoneyAmount.of(100, "INR", "en-IN")
    data.expense_by_category = [
        CategoryTotal(
            category_id=None,
            slug=name,
            name=name,
            icon=None,
            total=amount,
            count=1,
            share_percent=50,
        )
        for name in ("A", "B")
    ]
    data.top_merchants = [
        MerchantTotal(
            key="other",
            name="Other merchants",
            total=MoneyAmount.of(1000, "INR", "en-IN"),
            count=10,
            is_other=True,
        )
    ]
    facts = build_insights(data, PERIOD, "en-IN")
    assert [fact.kind for fact in facts] == ["spending_change", "largest_category"]
    assert "Joint largest" in facts[1].text
    assert facts[1].share_percent == 50
    data.top_merchants += [
        MerchantTotal(key=name, name=name, total=amount, count=1) for name in ("A", "B")
    ]
    fact = build_insights(data, PERIOD, "en-IN")[-1]
    assert fact.merchant_key == "A" and "Joint largest" in fact.text
