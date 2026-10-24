"""Turn a draft's first missing piece into one focused, typed question."""

from __future__ import annotations

from datetime import date

from finance_core.categories.schemas import CategoryView
from finance_core.dates import format_day, parse_iso_date
from finance_core.interactions import (
    ClarificationInteraction,
    ConfirmationInteraction,
    DraftPreview,
    Option,
)
from finance_core.money import (
    CURRENCY_EXPONENTS,
    SUPPORTED_CURRENCIES,
    MoneyError,
    exponent,
    format_money,
    to_minor,
)
from finance_core.schemas import MoneyAmount
from finance_core.transactions.schemas import PAYMENT_METHOD_LABELS
from finance_core.workflows.drafts import Issue, TransactionDraft

_COMMON_CURRENCIES = ("INR", "USD", "EUR", "GBP", "AED", "SGD")


def preview(draft: TransactionDraft, *, base_currency: str, locale: str, today: date) -> DraftPreview:
    amount: MoneyAmount | None = None
    value = draft.decimal_amount()
    currency = draft.effective_currency(base_currency)
    if value is not None and currency in SUPPORTED_CURRENCIES:
        try:
            amount = MoneyAmount.of(to_minor(value, currency), currency, locale)
        except MoneyError:
            amount = None
    occurred = parse_iso_date(draft.date)
    return DraftPreview(
        type=draft.type,
        amount=amount,
        category=draft.category_name or draft.category_text,
        occurred_on=occurred,
        occurred_on_label=format_day(occurred, today) if occurred else None,
        description=draft.description,
        merchant=draft.merchant,
        payment_method=PAYMENT_METHOD_LABELS.get(draft.payment_method or ""),
    )


def _what(draft: TransactionDraft) -> str | None:
    """How to refer to the transaction mid-sentence: "spend on dinner", "fits Swiggy"."""
    if draft.description:
        return draft.description.lower()
    return draft.merchant


def _formatted_amount(draft: TransactionDraft, base_currency: str, locale: str) -> str | None:
    value = draft.decimal_amount()
    currency = draft.effective_currency(base_currency)
    if value is None or currency not in SUPPORTED_CURRENCIES:
        return None
    try:
        return format_money(to_minor(value, currency), currency, locale)
    except MoneyError:
        return None


def build_question(
    issue: Issue,
    draft: TransactionDraft,
    *,
    draft_index: int,
    draft_count: int,
    round_number: int,
    base_currency: str,
    locale: str,
    today: date,
    category_options: list[CategoryView],
    notice: str | None = None,
) -> ClarificationInteraction | ConfirmationInteraction:
    interaction_id = f"q-{draft.id[:8]}-{issue.field}-{round_number}"
    what = _what(draft)
    amount_text = _formatted_amount(draft, base_currency, locale)
    draft_preview = preview(draft, base_currency=base_currency, locale=locale, today=today)
    prefix = f"{notice} " if notice else ""
    if draft_count > 1:
        prefix += f"({draft_index + 1} of {draft_count}) "
    common = {
        "id": interaction_id,
        "draft": draft_preview,
        "draft_index": draft_index,
        "draft_count": draft_count,
    }

    if issue.field == "amount_confirm":
        for_what = f" for {what}" if what else ""
        return ConfirmationInteraction(
            id=interaction_id,
            message=f"{prefix}Just to confirm: was it {amount_text}{for_what}?",
            reason="amount_unverified",
            confirm_label="Yes, that's right",
            cancel_label="No, change it",
            drafts=[draft_preview],
        )

    if issue.field == "amount":
        currency = draft.effective_currency(base_currency)
        if issue.reason == "precision" and currency in CURRENCY_EXPONENTS:
            places = exponent(currency)
            message = (
                f"{currency} amounts can have at most {places} decimal places. "
                "What was the exact amount?"
            )
        elif what and draft.type == "income":
            message = f"How much did you receive for {what}?"
        elif what:
            message = f"How much did you spend on {what}?"
        else:
            message = "What was the amount?"
        return ClarificationInteraction(
            message=prefix + message,
            field="amount",
            input_kind="amount",
            currency=currency if currency in SUPPORTED_CURRENCIES else base_currency,
            placeholder="e.g. 350",
            **common,
        )

    if issue.field == "currency":
        choices = [base_currency, *(c for c in _COMMON_CURRENCIES if c != base_currency)]
        return ClarificationInteraction(
            message=f"{prefix}I can't record {draft.currency} yet. Which currency was this in?",
            field="currency",
            input_kind="single_select",
            options=[Option(label=code, value=code) for code in choices],
            allow_custom_input=True,
            placeholder="Currency code, e.g. USD",
            **common,
        )

    if issue.field == "type":
        subject = f"{amount_text} for {what}" if what and amount_text else (amount_text or "this")
        return ClarificationInteraction(
            message=f"{prefix}Was {subject} money you spent or money you received?",
            field="type",
            input_kind="single_select",
            options=[
                Option(label="Expense", value="expense", description="Money out", icon="arrow-up-right"),
                Option(label="Income", value="income", description="Money in", icon="arrow-down-left"),
            ],
            **common,
        )

    if issue.field == "category":
        subject = what or (f"this {draft.type}" if draft.type else "this")
        return ClarificationInteraction(
            message=f"{prefix}Which category fits {subject}?",
            field="category",
            input_kind="single_select",
            options=[
                Option(label=c.name, value=c.slug, icon=c.icon) for c in category_options
            ],
            allow_custom_input=True,
            allow_skip=True,
            placeholder="Or type a new category",
            **common,
        )

    # date
    if issue.reason == "future":
        message = "That date is in the future. Which day did it happen?"
    elif issue.reason == "too_old":
        message = "That date looks too far back. Which day did it happen?"
    elif draft.date_text:
        message = f"Which day do you mean by “{draft.date_text}”?"
    else:
        message = "Which day was this?"
    return ClarificationInteraction(
        message=prefix + message,
        field="date",
        input_kind="date",
        max_date=today,
        **common,
    )
