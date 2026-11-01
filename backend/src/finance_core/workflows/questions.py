"""Turn a draft's first missing piece into one focused, typed question."""

from __future__ import annotations

from datetime import date

from finance_core.accounts.schemas import AccountView
from finance_core.categories.schemas import CategoryView
from finance_core.dates import format_day, parse_iso_date
from finance_core.friends.names import matching_friends
from finance_core.friends.schemas import FriendView
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


def preview(
    draft: TransactionDraft, *, base_currency: str, locale: str, today: date
) -> DraftPreview:
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
        account=draft.account_name or draft.account,
        to_account=draft.to_account_name or draft.to_account,
        shared_with=[person.display_name() for person in draft.people] if draft.is_shared() else [],
        paid_by=next((p.display_name() for p in draft.people if p.paid), None),
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
    account_options: list[AccountView] | None = None,
    friend_options: list[FriendView] | None = None,
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
                Option(
                    label="Expense", value="expense", description="Money out", icon="arrow-up-right"
                ),
                Option(
                    label="Income", value="income", description="Money in", icon="arrow-down-left"
                ),
            ],
            **common,
        )

    if issue.field == "category":
        subject = what or (f"this {draft.type}" if draft.type else "this")
        return ClarificationInteraction(
            message=f"{prefix}Which category fits {subject}?",
            field="category",
            input_kind="single_select",
            options=[Option(label=c.name, value=c.slug, icon=c.icon) for c in category_options],
            allow_custom_input=True,
            allow_skip=True,
            placeholder="Or type a new category",
            **common,
        )

    if issue.field in ("friend", "payer", "split"):
        return _sharing_question(
            issue, draft, prefix=prefix, base_currency=base_currency, locale=locale,
            friends=friend_options or [], common=common,
        )  # fmt: skip

    if issue.field in ("account", "to_account"):
        return _account_question(
            issue, draft, prefix=prefix, amount_text=amount_text,
            accounts=account_options or [], common=common,
        )  # fmt: skip

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


def _sharing_question(
    issue: Issue,
    draft: TransactionDraft,
    *,
    prefix: str,
    base_currency: str,
    locale: str,
    friends: list[FriendView],
    common: dict[str, object],
) -> ClarificationInteraction:
    """What a shared expense still needs: which friend a name means, who it is split with when
    a friend paid, or what each person had."""
    if issue.field == "friend":
        person = next(p for p in draft.people if not p.is_resolved())
        if issue.reason == "ambiguous":
            options = [
                Option(label=f.name, value=str(f.id), description=f.email)
                for f in matching_friends(person.said, friends)
            ]
            message = f"Which {person.said} do you mean?"
        else:
            # Existing friends stay on offer, so a misspelt name is one tap from the right person.
            options = [Option(label=f"Yes, add {person.display_name()}", value="add")] + [
                Option(label=f.name, value=str(f.id), description=f.email)
                for f in friends[:_MAX_FRIEND_OPTIONS]
            ]
            message = f"Add {person.display_name()} as a new friend?"
        return ClarificationInteraction(
            message=prefix + message, field="friend", input_kind="single_select",
            options=options, **common,
        )  # fmt: skip
    if issue.field == "payer":
        payer = next(p.display_name() for p in draft.people if p.paid)
        return ClarificationInteraction(
            message=(
                f"{prefix}A bill {payer} paid can only be split between you and the friend who "
                "paid. What should I do?"
            ),
            field="payer",
            input_kind="single_select",
            options=[
                Option(label="I paid it, split with everyone", value="i_paid"),
                Option(label=f"Split only between me and {payer}", value="only_payer"),
            ],
            **common,
        )
    # split
    currency = draft.effective_currency(base_currency)
    added = draft.exact_amounts_added()
    total = _formatted_amount(draft, base_currency, locale)
    if issue.reason == "mismatch" and added is not None and currency in SUPPORTED_CURRENCIES:
        shown = format_money(to_minor(added, currency), currency, locale)
        message = f"Those add up to {shown}, but the total is {total}. What did each of you have?"
    else:
        message = "What did each of you have?"
    first_friend = draft.people[0].display_name()
    return ClarificationInteraction(
        message=prefix + message,
        field="split",
        input_kind="single_select",
        options=[Option(label="Split it equally", value="equal")],
        allow_custom_input=True,
        placeholder=f"e.g. I had 400, {first_friend} 600",
        **common,
    )


def _account_question(
    issue: Issue,
    draft: TransactionDraft,
    *,
    prefix: str,
    amount_text: str | None,
    accounts: list[AccountView],
    common: dict[str, object],
) -> ClarificationInteraction:
    """Which account a transfer left, or went to. Offers the user's active accounts and
    takes a typed new name."""
    source = issue.field == "account"
    named = draft.account if source else draft.to_account
    if issue.reason == "same":
        prefix += "The money can't go to the account it came from. "
    elif issue.reason == "unknown" and named:
        prefix += f"I couldn't tell which of your accounts “{named}” is. "
    moved = f"the {amount_text}" if amount_text else "the money"
    question = (
        f"Which account did {moved} come from?" if source else f"Which account did {moved} go to?"
    )
    # The other end is never offered: a transfer needs two different accounts.
    other = None if source else draft.account_id
    options = [
        Option(label=a.name, value=str(a.id), icon=_ACCOUNT_ICONS.get(a.kind))
        for a in accounts
        if str(a.id) != other
    ][:_MAX_ACCOUNT_OPTIONS]
    other_end_name = (draft.to_account_name if source else draft.account_name) or ""
    if (
        not any(a.kind == "cash" for a in accounts)
        and other_end_name.casefold() != _CASH_NAME.casefold()
    ):
        # Most people hold cash but never set up an account for it. The option's value is the
        # name, so picking it is the same as typing "Cash": the account is created at save.
        # It is appended after the cap, so a long account list never pushes it out.
        options.append(Option(label=_CASH_NAME, value=_CASH_NAME, icon=_ACCOUNT_ICONS["cash"]))
    return ClarificationInteraction(
        message=prefix + question,
        field=issue.field,
        input_kind="single_select",
        options=options,
        allow_custom_input=True,
        placeholder="Or type a new account name",
        **common,
    )


_MAX_ACCOUNT_OPTIONS = 8
_MAX_FRIEND_OPTIONS = 8
_CASH_NAME = "Cash"
_ACCOUNT_ICONS = {
    "bank": "landmark", "credit_card": "credit-card", "wallet": "wallet", "cash": "banknote",
    "other": "circle-ellipsis",
}  # fmt: skip
