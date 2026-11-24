"""High-precision offline signals for explicit visual reports and deterministic insights."""

import re
from typing import Literal

from finance_core.llm.schemas import ReportSpec
from finance_core.money import SUPPORTED_CURRENCIES, normalize_currency

_BREAKDOWN = re.compile(
    r"\b(breakdown|break down|where did my money go|spending by category|"
    r"expenses by category|top merchants|largest (?:expense )?category|largest merchant)\b",
    re.I,
)
_INSIGHTS = re.compile(r"\binsights?\b|\bcompare (?:my )?(?:spending|expenses|income)\b", re.I)
_TREND = re.compile(r"\b(trends?|charts?|graphs?|plot|visuali[sz]e)\b", re.I)
_CURRENCY = re.compile(
    r"\b("
    + "|".join(sorted(SUPPORTED_CURRENCIES))
    + r"|rupees?|dollars?|euros?|pounds?|dirhams?|yen)\b|[₹$€£¥]",
    re.I,
)


def read_report_spec(text: str) -> ReportSpec | None:
    """Read chart/breakdown/insight wording, without supplying dates or monetary values."""
    # "How much did I spend, without charts?" remains a normal total question.
    words = re.sub(r"\b(?:no|without)\s+(?:charts?|graphs?|insights?)\b", "", text, flags=re.I)
    kind: Literal["trend", "breakdown", "insights"] | None = (
        "insights"
        if _INSIGHTS.search(words)
        else "breakdown"
        if _BREAKDOWN.search(words)
        else "trend"
        if _TREND.search(words)
        else None
    )
    if kind is None:
        return None
    match = _CURRENCY.search(words)
    currency = normalize_currency(match.group(0)) if match else None
    return ReportSpec(kind=kind, currency=currency)
