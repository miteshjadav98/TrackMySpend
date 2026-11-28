"""Auditable facts over server-produced report values; no predictions or model arithmetic."""

from babel.dates import format_date

from finance_core.reports.schemas import CurrencyReport, PeriodView, ReportInsight


def build_insights(report: CurrencyReport, period: PeriodView, locale: str) -> list[ReportInsight]:
    """Describe spending change and the leading category/named merchant when evidence exists."""
    date_locale = locale.replace("-", "_")
    dates = f"{format_date(period.start, locale=date_locale)} to {format_date(period.end, locale=date_locale)}"
    prefix = f"{dates} ({report.currency})"
    metric = report.expense
    facts: list[ReportInsight] = []
    if metric.current.amount_minor or metric.previous.amount_minor:
        if metric.previous.amount_minor == 0:
            sentence = (
                f"Spent {metric.current.formatted}; no previous spending in the comparison period."
            )
        elif metric.change.amount_minor == 0:
            sentence = (
                f"Spending was unchanged at {metric.current.formatted} from the comparison period."
            )
        else:
            sentence = (
                f"Spent {metric.current.formatted}, compared with {metric.previous.formatted} "
                f"in the preceding equal-length period (change: {metric.change.formatted})."
            )
        facts.append(
            ReportInsight(
                kind="spending_change",
                currency=report.currency,
                period=period,
                text=f"{prefix}: {sentence}",
                current=metric.current,
                previous=metric.previous,
                change=metric.change,
                change_percent=metric.change_percent,
            )
        )
    categories = report.expense_by_category
    if categories and categories[0].total.amount_minor > 0:
        first = categories[0]
        tied = sum(item.total.amount_minor == first.total.amount_minor for item in categories) > 1
        rank = "Joint largest" if tied else "Largest"
        facts.append(
            ReportInsight(
                kind="largest_category",
                currency=report.currency,
                period=period,
                text=f"{prefix}: {rank} expense category: {first.name}, {first.total.formatted}.",
                current=first.total,
                share_percent=first.share_percent,
                category_id=first.category_id,
            )
        )
    merchants = [item for item in report.top_merchants if not item.is_other]
    if merchants and merchants[0].total.amount_minor > 0:
        merchant = merchants[0]
        tied = sum(item.total.amount_minor == merchant.total.amount_minor for item in merchants) > 1
        rank = "Joint largest" if tied else "Largest"
        facts.append(
            ReportInsight(
                kind="largest_merchant",
                currency=report.currency,
                period=period,
                text=f"{prefix}: {rank} named merchant: {merchant.name}, {merchant.total.formatted}.",
                current=merchant.total,
                merchant_key=merchant.key,
            )
        )
    return facts
