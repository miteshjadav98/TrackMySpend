"""Deterministic reply composition.

Every number in a reply comes from the ledger (via the service layer), formatted by
code. The model never writes amounts, totals, or dates into a response, so a summary can
never disagree with the database.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any

from finance_core.dates import format_day
from finance_core.interactions import (
    Interaction,
    SuggestedPrompt,
    SuggestionsInteraction,
    SummaryInteraction,
    TransactionListInteraction,
    TransactionsSavedInteraction,
)
from finance_core.reports.schemas import CurrencySummary, PeriodView, SpendingSummary
from finance_core.schemas import MoneyAmount
from finance_core.transactions.schemas import PAYMENT_METHOD_LABELS, TransactionView

DEFAULT_SUGGESTIONS = [
    SuggestedPrompt(label="Add an expense", prompt="I spent ₹", mode="prefill", icon="plus"),
    SuggestedPrompt(label="Add income", prompt="I received ₹", mode="prefill", icon="arrow-down-left"),
    SuggestedPrompt(label="This month's spending", prompt="How much did I spend this month?", icon="pie-chart"),
    SuggestedPrompt(label="Recent transactions", prompt="Show my recent transactions", icon="list"),
]  # fmt: skip

_SUGGESTIONS_BY_OUTCOME: dict[str, list[SuggestedPrompt]] = {
    "saved": [
        SuggestedPrompt(label="This month's spending", prompt="How much did I spend this month?", icon="pie-chart"),
        SuggestedPrompt(label="Add another", prompt="I spent ₹", mode="prefill", icon="plus"),
    ],
    "summary": [
        SuggestedPrompt(label="Biggest expenses", prompt="Show my biggest expenses this month", icon="list"),
        SuggestedPrompt(label="Last month", prompt="Summarise last month", icon="calendar"),
    ],
    "search": [
        SuggestedPrompt(label="This month's spending", prompt="How much did I spend this month?", icon="pie-chart"),
        SuggestedPrompt(label="Add an expense", prompt="I spent ₹", mode="prefill", icon="plus"),
    ],
}  # fmt: skip


def suggestions_for(outcome: str | None, interaction_id: str) -> SuggestionsInteraction:
    prompts = _SUGGESTIONS_BY_OUTCOME.get(outcome or "", DEFAULT_SUGGESTIONS)
    return SuggestionsInteraction(id=interaction_id, prompts=prompts)


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def period_phrase(label: str) -> str:
    """'This week' -> 'this week' mid-sentence; 'October 2026' stays as is."""
    first = label.split(" ", 1)[0]
    return label[0].lower() + label[1:] if first in ("Today", "Yesterday", "This", "Last") else label


def compose_saved(
    saved: list[dict[str, Any]],
    *,
    today: date,
    locale: str,
    abandoned: bool,
    interaction_id: str,
) -> tuple[str, list[Interaction]]:
    views = [TransactionView.model_validate(item) for item in saved]
    totals: dict[str, int] = defaultdict(int)
    if len({view.type for view in views}) == 1:  # only total like with like
        for view in views:
            totals[view.currency] += view.amount_minor
    if len(views) == 1:
        tx = views[0]
        what = f" for {tx.description}" if tx.description else ""
        category = f" under {tx.category.name}" if tx.category else ""
        paid = (
            f", paid by {PAYMENT_METHOD_LABELS[tx.payment_method]}"
            if tx.payment_method and tx.type == "expense"
            else ""
        )
        noun = "expense" if tx.type == "expense" else "income"
        day = format_day(tx.occurred_on, today)
        when = day if day in ("today", "yesterday") else f"on {day}"
        text = f"Saved {tx.amount_formatted} {noun}{what}{category} {when}{paid}."
    else:
        items = [
            f"{tx.amount_formatted} {tx.description or (tx.category.name if tx.category else '')}".strip()
            for tx in views
        ]
        text = f"Saved {len(views)} transactions: {_join(items)}."
    if abandoned:
        text = "I set aside the earlier unfinished entry. " + text
    total_amounts = [
        MoneyAmount.of(minor, currency, locale) for currency, minor in totals.items()
    ] if len(views) > 1 else []
    card = TransactionsSavedInteraction(id=interaction_id, transactions=views, totals=total_amounts)
    return text, [card]


def _currency_sentence(cs: CurrencySummary, label: str) -> str:
    parts: list[str] = []
    if cs.expense_count:
        plural = "s" if cs.expense_count != 1 else ""
        parts.append(f"spent {cs.expense.formatted} across {cs.expense_count} expense{plural}")
    if cs.income_count:
        parts.append(f"received {cs.income.formatted}")
    sentence = f"{label}: you {_join(parts)}." if parts else ""
    top = [c for c in cs.expense_by_category[:3]]
    if top:
        tops = ", ".join(f"{c.name} {c.total.formatted} ({c.share_percent:g}%)" for c in top)
        sentence += f" Top categories: {tops}."
    return sentence


def compose_summary(
    summary_data: dict[str, Any], focus: dict[str, Any] | None, *, interaction_id: str
) -> tuple[str, list[Interaction]]:
    summary = SpendingSummary.model_validate(summary_data)
    label = summary.period.label
    if summary.transaction_count == 0:
        text = (
            f"You haven't recorded any transactions for {period_phrase(label)} yet. "
            "Try “Spent ₹250 on lunch today”."
        )
        return text, [SummaryInteraction(id=interaction_id, summary=summary)]

    lines: list[str] = []
    focus_slug = (focus or {}).get("category")
    if focus_slug:
        for cs in summary.currencies:
            match = next((c for c in cs.expense_by_category + cs.income_by_category if c.slug == focus_slug), None)
            if match:
                plural = "s" if match.count != 1 else ""
                lines.append(f"{match.name} in {label}: {match.total.formatted} across {match.count} transaction{plural}.")
                break
        else:
            lines.append(f"Nothing recorded under that category for {label}.")
    primary = summary.currencies[0]
    lines.append(_currency_sentence(primary, label))
    others = [cs.currency for cs in summary.currencies[1:]]
    if others:
        lines.append(f"You also have transactions in {_join(others)} (shown separately).")
    return " ".join(line for line in lines if line), [SummaryInteraction(id=interaction_id, summary=summary)]


def compose_search(results: dict[str, Any], *, interaction_id: str) -> tuple[str, list[Interaction]]:
    items = [TransactionView.model_validate(item) for item in results.get("items", [])]
    period = PeriodView.model_validate(results["period"]) if results.get("period") else None
    title = results.get("title") or "Transactions"
    when = f" for {period_phrase(period.label)}" if period else ""
    if not items:
        text = f"I couldn't find any matching transactions{when}."
    elif len(items) == 1:
        tx = items[0]
        text = f"{title}{when}: {tx.amount_formatted}" + (f" for {tx.description}" if tx.description else "") + f" on {tx.occurred_on:%d %b}."
    else:
        text = f"Here are {len(items)} {title.lower()}{when}."
    card = TransactionListInteraction(
        id=interaction_id,
        title=title,
        period=period,
        transactions=items,
        has_more=bool(results.get("hasMore")),
    )
    return text, [card]


STATIC_REPLIES: dict[str, str] = {
    "cancelled": "Okay, I won't save that.",
    "gave_up": (
        "I couldn't complete that entry. Try again with something like "
        "“Spent ₹350 on dinner yesterday”, or add it from the Transactions page."
    ),
    "nothing_to_record": (
        "I couldn't find an amount in that. Tell me what it was for and how much, "
        "for example “Spent ₹120 on coffee”."
    ),
    "llm_unavailable": (
        "I'm having trouble understanding messages right now. You can still add "
        "transactions from the Transactions page."
    ),
    "save_failed": "I couldn't save that because something changed. Please try again.",
}
