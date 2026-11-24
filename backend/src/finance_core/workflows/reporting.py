"""Build a fixed chat report from the authoritative overview, keeping checkpoints bounded."""

from urllib.parse import urlencode

from finance_core.interactions import ReportInteraction
from finance_core.llm.schemas import ReportSpec
from finance_core.money import SUPPORTED_CURRENCIES
from finance_core.reports.schemas import ReportOverview


def report_interaction(
    overview: ReportOverview, request: ReportSpec, interaction_id: str
) -> ReportInteraction:
    """Keep one currency, at most 120 trend buckets, five categories and three merchants."""
    currency = (request.currency or overview.base_currency).upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ValueError("Choose a supported ISO currency for the report.")
    selected = next((item for item in overview.currencies if item.currency == currency), None)
    preview = (
        selected.model_copy(
            update={
                "trend": selected.trend[:120] if request.kind == "trend" else [],
                "expense_by_category": selected.expense_by_category[:5]
                if request.kind == "breakdown"
                else [],
                "top_merchants": selected.top_merchants[:3] if request.kind == "breakdown" else [],
                "insights": selected.insights[:3] if request.kind == "insights" else [],
            }
        )
        if selected
        else None
    )
    params = urlencode(
        {
            "period": "range",
            "start": overview.period.start.isoformat(),
            "end": overview.period.end.isoformat(),
            "currency": currency,
        }
    )
    return ReportInteraction(
        id=interaction_id,
        kind=request.kind,
        period=overview.period,
        comparison_period=overview.comparison_period,
        currency=currency,
        available_currencies=list(
            dict.fromkeys(
                [overview.base_currency, *(item.currency for item in overview.currencies)]
            )
        ),
        preview=preview,
        transaction_count=overview.transaction_count,
        generated_at=overview.generated_at,
        report_href=f"/reports?{params}",
    )
