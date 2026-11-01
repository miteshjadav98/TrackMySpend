"""Apply the user's answer to the pending question, deterministically.

A tapped option or submitted control is validated against what was actually offered.
Free text is first parsed for the field in question (an amount, a date, yes/no, a category
name); only if that fails is it handed back to the model, which decides whether it is an
answer or a brand-new request.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from finance_core.accounts.names import resolve_account_name
from finance_core.accounts.schemas import AccountView
from finance_core.categories.service import CategoryService
from finance_core.dates import day_first_for_locale, parse_iso_date, resolve_date_expression
from finance_core.friends.names import resolve_friend_name
from finance_core.friends.schemas import FriendView
from finance_core.llm.rules import classify
from finance_core.llm.sharing import amounts_by_person
from finance_core.money import find_amounts, normalize_currency, parse_amount_with_currency
from finance_core.workflows.drafts import TransactionDraft, merge_repeated_people

AnswerKind = Literal["applied", "invalid", "cancel_all", "not_an_answer"]

_I = re.IGNORECASE
_YES = re.compile(
    r"^\s*(y|ya|yes|yeah|yep|yup|sure|correct|right|ok|okay|confirm|save|that'?s right|haan|ha)\b",
    _I,
)
_NO = re.compile(r"^\s*(n|no|nope|nah|wrong|incorrect|not right|change)\b", _I)
_CANCEL_ALL = re.compile(
    r"^\s*(cancel|never\s?mind|forget it|stop|discard|don'?t save|leave it)\b", _I
)
_EXPENSE = re.compile(r"\b(expense|spent|spend|paid|out|outgoing|debit|debited)\b", _I)
_INCOME = re.compile(r"\b(income|received|earned|in|incoming|credit|credited)\b", _I)
_NAME_LIKE = re.compile(r"^[A-Za-z][A-Za-z &'\-]{0,39}$")
# Replies that say "I can't answer" and must never become an account or category name.
NON_ANSWERS = frozenset({
    "idk", "dk", "dunno", "skip", "not sure", "unsure", "dont know", "no idea", "none",
    "nothing", "whatever", "no clue",
})  # fmt: skip
_EQUALLY = re.compile(r"\b(equal|equally|evenly|even|50[/-]50)\b", _I)
_ACCOUNT_NAME_LIKE = re.compile(r"^[A-Za-z][\w &'.\-]{0,59}$")


@dataclass(frozen=True, slots=True)
class AnswerOutcome:
    kind: AnswerKind
    draft: TransactionDraft | None = None
    notice: str | None = None


def pending_field(pending: dict[str, Any]) -> str:
    return "amount_confirm" if pending.get("type") == "confirmation" else str(pending.get("field"))


def _applied(draft: TransactionDraft, **changes: Any) -> AnswerOutcome:
    return AnswerOutcome("applied", draft=draft.model_copy(update=changes))


def _with_type(draft: TransactionDraft, kind: str) -> AnswerOutcome:
    # A category belongs to one type, so the draft's category is worked out again.
    return _applied(draft, type=kind, category_id=None, category_name=None, category_source=None)


def _invalid(notice: str) -> AnswerOutcome:
    return AnswerOutcome("invalid", notice=notice)


def _plain(value: Any) -> str:
    return format(value.normalize(), "f")


def is_a_non_answer(text: str) -> bool:
    """True for "idk", "don't know", "?" and the like, however they are cased or punctuated."""
    plain = " ".join(re.sub(r"[^\w\s]", "", text.replace("'", "")).casefold().split())
    return plain in NON_ANSWERS or not plain


def _looks_like_category_name(text: str) -> bool:
    return _looks_like_a_name(text, _NAME_LIKE)


def _looks_like_a_name(text: str, pattern: re.Pattern[str]) -> bool:
    """Free text that is a short name ("Hobbies", "Axis Bank"), not a request or a yes/no."""
    stripped = text.strip()
    return (
        bool(pattern.match(stripped))
        and len(stripped.split()) <= 3
        and not find_amounts(stripped)
        and classify(stripped) in ("help", "smalltalk")
        and not _YES.match(stripped)
        and not _NO.match(stripped)
    )


class AnswerApplier:
    def __init__(
        self,
        categories: CategoryService,
        *,
        user_id: uuid.UUID,
        today: date,
        locale: str,
        accounts: Sequence[AccountView] = (),
        friends: Sequence[FriendView] = (),
    ) -> None:
        self._categories = categories
        self._accounts = accounts  # the user's active accounts, for account answers
        self._friends = friends  # the user's active friends, for friend answers
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
        allow_custom = (field == "category" and _looks_like_category_name(text)) or (
            field in ("account", "to_account") and _looks_like_a_name(text, _ACCOUNT_NAME_LIKE)
        )
        if field in ("category", "account", "to_account") and is_a_non_answer(text):
            # Not a new request either: ask the same question again.
            return await self.apply_value(field, text, draft, allow_custom=True)
        outcome = await self.apply_value(field, text, draft, allow_custom=allow_custom)
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
                return _with_type(draft, lowered)
            if _EXPENSE.search(text) and not _INCOME.search(text):
                return _with_type(draft, "expense")
            if _INCOME.search(text) and not _EXPENSE.search(text):
                return _with_type(draft, "income")
            return _invalid("Was it money out (expense) or money in (income)?")
        if field == "category":
            kind: Literal["expense", "income"] = "income" if draft.type == "income" else "expense"
            category = await self._categories.match(self._user_id, text, kind)
            if category is not None:
                return _applied(
                    draft,
                    category_id=str(category.id),
                    category_name=category.name,
                    category_source="picked",  # the user's own pick outranks everything
                    category_text=None,
                    category_skipped=False,
                )
            if allow_custom and is_a_non_answer(text):
                return _invalid("Tell me a category name, or tap Skip.")
            if allow_custom and _NAME_LIKE.match(text):
                return _applied(draft, category_text=text.title()[:64], category_skipped=False)
            return _invalid("I couldn't match that to a category.")
        if field in ("account", "to_account"):
            return self._apply_account(field, text, draft, allow_custom=allow_custom)
        if field == "friend":
            return self._apply_friend(text, draft)
        if field == "payer":
            return self._apply_payer(text, draft)
        if field == "split":
            return self._apply_split(text, draft)
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

    def _apply_account(
        self, field: str, text: str, draft: TransactionDraft, *, allow_custom: bool
    ) -> AnswerOutcome:
        """A tapped account (its id), one of the user's accounts by name, or a new name."""
        account = next((a for a in self._accounts if str(a.id) == text), None)
        account = account or resolve_account_name(text, self._accounts)
        prefix = "account" if field == "account" else "to_account"
        if account is not None:
            return _applied(draft, **{
                f"{prefix}_id": str(account.id), f"{prefix}_name": account.name,
                f"{prefix}_new": False,
            })  # fmt: skip
        if allow_custom and is_a_non_answer(text):
            return _invalid("Tell me which account, or type a new account name.")
        if allow_custom and _ACCOUNT_NAME_LIKE.match(text):
            # Created at save, so a question abandoned halfway leaves no stray account.
            return _applied(draft, **{
                f"{prefix}_id": None, f"{prefix}_name": text[:60], f"{prefix}_new": True,
            })  # fmt: skip
        return _invalid("I couldn't match that to one of your accounts.")

    def _apply_friend(self, text: str, draft: TransactionDraft) -> AnswerOutcome:
        """Settle the first unresolved name: add them as a new friend, or pick an existing one
        (a tapped friend's id, or their name typed out)."""
        index = next((i for i, p in enumerate(draft.people) if not p.is_resolved()), None)
        if index is None:
            return _invalid("Everyone in that expense is already settled.")
        person = draft.people[index]
        if text.casefold() == "add" or _YES.match(text):
            settled = person.model_copy(
                update={"is_new": True, "ambiguous": False, "name": _tidy_new_name(person.said)}
            )
        else:
            friend = next((f for f in self._friends if str(f.id) == text), None)
            friend = friend or resolve_friend_name(text, self._friends)
            if friend is None:
                return _invalid("Tap one of your friends, or say yes to add them as a new friend.")
            settled = person.model_copy(
                update={"friend_id": str(friend.id), "name": friend.name, "ambiguous": False}
            )
        people = [*draft.people[:index], settled, *draft.people[index + 1 :]]
        return _applied(draft, people=merge_repeated_people(people))

    @staticmethod
    def _apply_payer(text: str, draft: TransactionDraft) -> AnswerOutcome:
        """When a friend paid but more than one friend shares: the user paid after all, or the
        expense is narrowed to the user and the friend who paid."""
        if text == "i_paid":
            return _applied(
                draft, people=[p.model_copy(update={"paid": False}) for p in draft.people]
            )
        if text == "only_payer":
            return _applied(draft, people=[p for p in draft.people if p.paid])
        return _invalid("Please pick one of the options.")

    @staticmethod
    def _apply_split(text: str, draft: TransactionDraft) -> AnswerOutcome:
        """Back to an equal split, or new exact amounts for the user and every friend."""
        if _EQUALLY.search(text):
            people = [p.model_copy(update={"amount": None}) for p in draft.people]
            return _applied(draft, split="equal", my_amount=None, people=people)
        said = amounts_by_person(text, [p.said for p in draft.people])
        wanted = ["me", *(p.said.casefold() for p in draft.people)]
        if any(key not in said for key in wanted):
            return _invalid("Tell me what each of you had, like “I had 400, Jaymin 600”.")
        people = [
            p.model_copy(update={"amount": _plain(said[p.said.casefold()])}) for p in draft.people
        ]
        return _applied(draft, split="exact", my_amount=_plain(said["me"]), people=people)


def _tidy_new_name(said: str) -> str:
    # A name typed in lower case is saved capitalised; "McKay" keeps its capitals.
    return said.title() if said.islower() else said
