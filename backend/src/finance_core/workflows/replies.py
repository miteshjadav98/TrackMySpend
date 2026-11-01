"""Deterministic reply composition.

Every number in a reply comes from the ledger (via the service layer), formatted by
code. The model never writes amounts, totals, or dates into a response, so a summary can
never disagree with the database.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any

from finance_core.dates import format_day
from finance_core.friends.schemas import SharedExpenseView
from finance_core.interactions import (
    Interaction,
    SuggestedPrompt,
    SuggestionsInteraction,
    SummaryInteraction,
    TransactionListInteraction,
    TransactionsSavedInteraction,
)
from finance_core.money import find_amounts
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
    return (
        label[0].lower() + label[1:] if first in ("Today", "Yesterday", "This", "Last") else label
    )


def _merchant_rule_note(tx: TransactionView) -> str:
    """Why a merchant rule chose the category, e.g. "Filed under Office meals, as before for
    Swiggy"."""
    category = tx.category.name if tx.category else ""
    return f"Filed under {category}, as before for {tx.merchant}."


def _route(tx: TransactionView) -> str:
    """ "HDFC → Paytm" for a transfer, from the two accounts it saved with."""
    source = tx.account.name if tx.account else "?"
    target = tx.to_account.name if tx.to_account else "?"
    return f"{source} → {target}"


def _via_account(tx: TransactionView) -> str:
    """ " from HDFC" for a tagged expense, " into HDFC" for tagged income, else nothing."""
    if tx.account is None:
        return ""
    return f" {'from' if tx.type == 'expense' else 'into'} {tx.account.name}"


def _summary_item(tx: TransactionView, shared_by_id: dict[Any, SharedExpenseView]) -> str:
    """One entry of "Saved 3 transactions: ...": amount and what it was for, or the route."""
    expense = shared_by_id.get(tx.shared_expense_id)
    if expense is not None:
        friends = _join([share.name for share in expense.shares if not share.is_you])
        return f"{expense.total_formatted} {tx.description or 'expense'} shared with {friends}"
    what = (
        _route(tx)
        if tx.type == "transfer"
        else tx.description or (tx.category.name if tx.category else "")
    )
    return f"{tx.amount_formatted} {what}".strip()


def _unmatched_account_note(names: Sequence[str]) -> str:
    quoted = _join([f"“{name}”" for name in names])
    return f"I couldn't match {quoted} to one of your accounts, so I saved it without an account."


def _shared_note(expense: SharedExpenseView) -> str:
    """ "You paid. Shares: You ₹500.00, Jaymin ₹500.00." from the saved shared expense."""
    payer = "You" if expense.paid_by_you else expense.payer.name
    shares = ", ".join(f"{share.name} {share.amount_formatted}" for share in expense.shares)
    return f"{payer} paid. Shares: {shares}."


def _added_friends_note(names: Sequence[str]) -> str:
    return f"I added {_join(list(names))} to your friends."


def compose_saved(
    saved: list[dict[str, Any]],
    *,
    today: date,
    locale: str,
    abandoned: bool,
    interaction_id: str,
    filed_by_merchant_rule: frozenset[str] = frozenset(),
    unmatched_accounts: Sequence[str] = (),
    shared: Sequence[dict[str, Any]] = (),
    added_friends: Sequence[str] = (),
) -> tuple[str, list[Interaction]]:
    views = [TransactionView.model_validate(item) for item in saved]
    shared_views = [SharedExpenseView.model_validate(item) for item in shared]
    shared_by_id = {expense.id: expense for expense in shared_views}
    by_rule = [tx for tx in views if str(tx.id) in filed_by_merchant_rule]
    totals: dict[str, int] = defaultdict(int)
    if len({view.type for view in views}) == 1:  # only total like with like
        for view in views:
            totals[view.currency] += view.amount_minor
    if len(views) == 1:
        tx = views[0]
        what = f" for {tx.description}" if tx.description else ""
        # A merchant rule's category is named in the note below, with the reason.
        category = f" under {tx.category.name}" if tx.category and not by_rule else ""
        paid = (
            f", paid by {PAYMENT_METHOD_LABELS[tx.payment_method]}"
            if tx.payment_method and tx.type == "expense"
            else ""
        )
        day = format_day(tx.occurred_on, today)
        when = day if day in ("today", "yesterday") else f"on {day}"
        if tx.shared_expense_id in shared_by_id:
            expense = shared_by_id[tx.shared_expense_id]
            text = (
                f"Saved {expense.total_formatted} shared expense{what}{category}"
                f"{_via_account(tx)} {when}. {_shared_note(expense)}"
            )
        elif tx.type == "transfer":
            source = tx.account.name if tx.account else "?"
            target = tx.to_account.name if tx.to_account else "?"
            text = f"Saved {tx.amount_formatted} transfer from {source} to {target} {when}."
        else:
            noun = "expense" if tx.type == "expense" else "income"
            text = f"Saved {tx.amount_formatted} {noun}{what}{category}{_via_account(tx)} {when}{paid}."
    else:
        items = [_summary_item(tx, shared_by_id) for tx in views]
        text = f"Saved {len(views)} transactions: {_join(items)}."
    for tx in by_rule:
        text += " " + _merchant_rule_note(tx)
    if added_friends:
        text += " " + _added_friends_note(added_friends)
    if unmatched_accounts:
        text += " " + _unmatched_account_note(unmatched_accounts)
    if abandoned:
        text = "I set aside the earlier unfinished entry. " + text
    total_amounts = (
        [MoneyAmount.of(minor, currency, locale) for currency, minor in totals.items()]
        if len(views) > 1
        else []
    )
    card = TransactionsSavedInteraction(
        id=interaction_id, transactions=views, totals=total_amounts, shared=shared_views
    )
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
            match = next(
                (c for c in cs.expense_by_category + cs.income_by_category if c.slug == focus_slug),
                None,
            )
            if match:
                plural = "s" if match.count != 1 else ""
                lines.append(
                    f"{match.name} in {label}: {match.total.formatted} across {match.count} transaction{plural}."
                )
                break
        else:
            lines.append(f"Nothing recorded under that category for {label}.")
    primary = summary.currencies[0]
    lines.append(_currency_sentence(primary, label))
    others = [cs.currency for cs in summary.currencies[1:]]
    if others:
        lines.append(f"You also have transactions in {_join(others)} (shown separately).")
    return " ".join(line for line in lines if line), [
        SummaryInteraction(id=interaction_id, summary=summary)
    ]


def compose_search(
    results: dict[str, Any], *, interaction_id: str
) -> tuple[str, list[Interaction]]:
    items = [TransactionView.model_validate(item) for item in results.get("items", [])]
    period = PeriodView.model_validate(results["period"]) if results.get("period") else None
    title = results.get("title") or "Transactions"
    when = f" for {period_phrase(period.label)}" if period else ""
    if not items:
        text = f"I couldn't find any matching transactions{when}."
    elif len(items) == 1:
        tx = items[0]
        text = (
            f"{title}{when}: {tx.amount_formatted}"
            + (f" for {tx.description}" if tx.description else "")
            + f" on {tx.occurred_on:%d %b}."
        )
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


# The reply prompt's own example amount; any other figure in a free-form reply is invented.
_ALLOWED_REPLY_AMOUNTS = frozenset({Decimal(350)})


def reply_is_grounded(reply: str, user_text: str) -> bool:
    """False if a free-form model reply mentions an amount the user never wrote.

    Free-form replies are not computed from the ledger, so any figure in them would be
    invented. The caller then falls back to a canned reply.
    """
    allowed = _ALLOWED_REPLY_AMOUNTS | {m.value for m in find_amounts(user_text)}
    return bool(reply.strip()) and all(m.value in allowed for m in find_amounts(reply))


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
    "transfer_currency_mismatch": (
        "Transfers between accounts in different currencies aren't supported. "
        "Both accounts, and the amount, need to be in the same currency."
    ),
    "account_limit": (
        "You've reached the limit of active accounts, so I couldn't add a new one. "
        "Archive an account you no longer use, then try again."
    ),
    "save_failed": "I couldn't save that because something changed. Please try again.",
}
