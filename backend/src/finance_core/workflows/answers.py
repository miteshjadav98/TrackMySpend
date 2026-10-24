"""Apply the user's answer to the pending question, deterministically.

A tapped option or submitted control is validated against what was actually offered.
Free text is first parsed for the field in question (an amount, a date, yes/no, a category
name); only if that fails is it handed back to the model, which decides whether it is an
answer or a brand-new request.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from finance_core.categories.service import CategoryService
from finance_core.dates import day_first_for_locale, parse_iso_date, resolve_date_expression
from finance_core.llm.rules import classify
from finance_core.money import find_amounts, normalize_currency, parse_amount_with_currency
from finance_core.workflows.drafts import TransactionDraft

AnswerKind = Literal["applied", "invalid", "cancel_all", "not_an_answer"]

_I = re.IGNORECASE
_YES = re.compile(
    r"^\s*(y|ya|yes|yeah|yep|yup|sure|correct|right|ok|okay|confirm|save|that'?s right|haan|ha)\b", _I
)
_NO = re.compile(r"^\s*(n|no|nope|nah|wrong|incorrect|not right|change)\b", _I)
_CANCEL_ALL = re.compile(
    r"^\s*(cancel|never\s?mind|forget it|stop|discard|don'?t save|leave it)\b", _I
)
_EXPENSE = re.compile(r"\b(expense|spent|spend|paid|out|outgoing|debit|debited)\b", _I)
_INCOME = re.compile(r"\b(income|received|earned|in|incoming|credit|credited)\b", _I)
_NAME_LIKE = re.compile(r"^[A-Za-z][A-Za-z &'\-]{0,39}$")


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    kind: AnswerKind
    draft: TransactionDraft | None = None
    notice: str | None = None


def pending_field(pending: dict[str, Any]) -> str:
    return "amount_confirm" if pending.get("type") == "confirmation" else str(pending.get("field"))


def _applied(draft: TransactionDraft, **changes: Any) -> AnswerOutcome:
    return AnswerOutcome("applied", draft=draft.model_copy(update=changes))


def _invalid(notice: str) -> AnswerOutcome:
    return AnswerOutcome("invalid", notice=notice)


def _plain(value: Any) -> str:
    return format(value.normalize(), "f")


def _looks_like_category_name(text: str) -> bool:
    stripped = text.strip()
    return (
        bool(_NAME_LIKE.match(stripped))
        and len(stripped.split()) <= 3
        and not find_amounts(stripped)
        and classify(stripped) in ("help", "smalltalk")
        and not _YES.match(stripped)
        and not _NO.match(stripped)
    )


class AnswerApplier:
    def __init__(
        self, categories: CategoryService, *, user_id: uuid.UUID, today: date, locale: str
    ) -> None:
        self._categories = categories
        self._user_id = user_id
        self._today = today
        self._locale = locale

    async def from_response(
        self, pending: dict[str, Any], response: dict[str, Any], draft: TransactionDraft
    ) -> AnswerOutcome:
        field = pending_field(pending)
        action = response.get("action")
        if action == "cancel":
            if field == "amount_confirm":
                return _applied(draft, amount=None, amount_confirmed=False)
            return AnswerOutcome("cancel_all")
        if action == "skip":
            if field == "category" and pending.get("allowSkip"):
                return _applied(draft, category_skipped=True, category_text=None)
            return _invalid("That question can't be skipped.")
        if field == "amount_confirm":
            return _applied(draft, amount_confirmed=True)

        value = response.get("value")
        text = value[0] if isinstance(value, list) and value else value
        if not isinstance(text, str) or not text.strip():
            return _invalid("I didn't get an answer there.")
        if pending.get("inputKind") in ("single_select", "multi_select"):
            offered = {option.get("value") for option in pending.get("options", [])}
            if text not in offered and not pending.get("allowCustomInput"):
                return _invalid("Please pick one of the options.")
        return await self.apply_value(
            field, text, draft, allow_custom=bool(pending.get("allowCustomInput"))
        )

    async def from_text(
        self, pending: dict[str, Any], text: str, draft: TransactionDraft
    ) -> AnswerOutcome:
        field = pending_field(pending)
        if _CANCEL_ALL.match(text) and field != "amount_confirm":
            return AnswerOutcome("cancel_all")
        if field == "amount_confirm":
            mentions = find_amounts(text)
            if _NO.match(text) or (mentions and not _YES.match(text)):
                if len(mentions) == 1:  # "no, it was 400"
                    m = mentions[0]
                    return _applied(
                        draft,
                        amount=_plain(m.value),
                        amount_confirmed=True,
                        currency=m.currency or draft.currency,
                    )
                return _applied(draft, amount=None, amount_confirmed=False)
            if _YES.match(text):
                return _applied(draft, amount_confirmed=True)
            return AnswerOutcome("not_an_answer")
        outcome = await self.apply_value(
            field, text, draft, allow_custom=field == "category" and _looks_like_category_name(text)
        )
        # Free text that does not parse as an answer is more likely a new request.
        return outcome if outcome.kind == "applied" else AnswerOutcome("not_an_answer")

    async def apply_value(
        self, field: str, text: str, draft: TransactionDraft, *, allow_custom: bool = False
    ) -> AnswerOutcome:
        text = text.strip()
        if field == "amount":
            parsed = parse_amount_with_currency(text)
            if parsed is None and (mentions := find_amounts(text)):
                parsed = (mentions[0].value, mentions[0].currency)
            if parsed is None:
                return _invalid("That doesn't look like an amount.")
            value, currency = parsed
            return _applied(
                draft,
                amount=_plain(value),
                amount_confirmed=True,
                currency=currency or draft.currency,
            )
        if field == "currency":
            code = normalize_currency(text)
            if code is None:
                return _invalid("I don't recognise that currency.")
            return _applied(draft, currency=code)
        if field == "type":
            lowered = text.lower()
            if lowered in ("expense", "income"):
                return _applied(draft, type=lowered, category_id=None, category_name=None)
            if _EXPENSE.search(text) and not _INCOME.search(text):
                return _applied(draft, type="expense", category_id=None, category_name=None)
            if _INCOME.search(text) and not _EXPENSE.search(text):
                return _applied(draft, type="income", category_id=None, category_name=None)
            return _invalid("Was it money out (expense) or money in (income)?")
        if field == "category":
            kind = draft.type or "expense"
            category = await self._categories.match(self._user_id, text, kind)
            if category is not None:
                return _applied(
                    draft,
                    category_id=str(category.id),
                    category_name=category.name,
                    category_text=None,
                    category_skipped=False,
                )
            if allow_custom and _NAME_LIKE.match(text):
                return _applied(draft, category_text=text.title()[:64], category_skipped=False)
            return _invalid("I couldn't match that to a category.")
        if field == "date":
            occurred = parse_iso_date(text) or resolve_date_expression(
                text, self._today, day_first=day_first_for_locale(self._locale)
            )
            if occurred is None:
                return _invalid("I couldn't work out that date.")
            if occurred > self._today:
                return _invalid("That date is in the future.")
            return _applied(draft, date=occurred.isoformat(), date_assumed=False)
        return _invalid("Sorry, I didn't follow that.")
