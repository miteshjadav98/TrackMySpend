"""Clarification logic, tested without a model, a database, or a graph."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

import pytest

from finance_core.llm.schemas import ExtractedTransaction
from finance_core.workflows.answers import AnswerApplier
from finance_core.workflows.drafts import TransactionDraft, draft_from_extraction, first_issue
from finance_core.workflows.questions import build_question
from finance_core.workflows.replies import period_phrase, reply_is_grounded

TODAY = date(2026, 10, 24)


def draft(**fields: Any) -> TransactionDraft:
    base: dict[str, Any] = {
        "id": "d1a2b3c4-0000",
        "origin_message_id": "m1",
        "type": "expense",
        "amount": "350",
        "amount_confirmed": True,
        "category_id": str(uuid.uuid4()),
        "category_name": "Food & Dining",
        "date": "2026-10-23",
        "description": "Dinner",
    }
    base.update(fields)
    return TransactionDraft(**base)


def extract(text: str, **fields: Any) -> TransactionDraft:
    return draft_from_extraction(
        ExtractedTransaction(**fields),
        draft_id="d-1",
        origin_message_id="m-1",
        source_text=text,
        today=TODAY,
        locale="en-IN",
    )


# -- drafts -------------------------------------------------------------------------------


def test_amount_typed_by_the_user_is_trusted() -> None:
    result = extract("spent 350 on dinner", type="expense", amount="350")
    assert result.amount == "350" and result.amount_confirmed


def test_amount_the_model_inferred_must_be_confirmed() -> None:
    result = extract("three fifty on dinner", type="expense", amount="350")
    assert result.amount == "350" and not result.amount_confirmed


def test_our_date_resolver_overrides_the_models_date() -> None:
    result = extract("dinner yesterday 350", amount="350", date_text="yesterday", date="2026-10-20")
    assert result.date == "2026-10-23"


def test_missing_date_means_today_and_is_flagged() -> None:
    result = extract("dinner 350", amount="350")
    assert result.date == "2026-10-24" and result.date_assumed


def test_vague_date_is_left_for_a_question() -> None:
    result = extract("uber 1200 this week", amount="1200", date_text="this week")
    assert result.date is None
    assert first_issue(result.model_copy(update={"type": "expense", "category_id": "x"}),
                       base_currency="INR", today=TODAY).field == "date"  # fmt: skip


def test_unsupported_currency_is_kept_so_we_can_ask() -> None:
    result = extract("spent 20 xyz", amount="20", currency="XYZ")
    assert result.currency == "XYZ"


# -- what to ask next -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "field", "reason"),
    [
        ({"amount": None}, "amount", "missing"),
        ({"amount": "350.555"}, "amount", "precision"),
        ({"currency": "XYZ"}, "currency", "unsupported"),
        ({"amount_confirmed": False}, "amount_confirm", "unverified"),
        ({"type": None}, "type", "missing"),
        ({"category_id": None}, "category", "missing"),
        ({"date": None}, "date", "missing"),
        ({"date": "2026-10-30"}, "date", "future"),
        ({"date": "1985-01-01"}, "date", "too_old"),
    ],
)
def test_first_issue(fields: dict, field: str, reason: str) -> None:
    issue = first_issue(draft(**fields), base_currency="INR", today=TODAY)
    assert issue is not None and (issue.field, issue.reason) == (field, reason)


def test_complete_draft_has_no_issue() -> None:
    assert first_issue(draft(), base_currency="INR", today=TODAY) is None
    assert (
        first_issue(
            draft(category_id=None, category_skipped=True), base_currency="INR", today=TODAY
        )
        is None
    )


def test_amount_is_asked_before_anything_else() -> None:
    issue = first_issue(
        draft(amount=None, type=None, category_id=None, date=None), base_currency="INR", today=TODAY
    )
    assert issue is not None and issue.field == "amount"


def test_questions_are_typed_and_specific() -> None:
    issue = first_issue(draft(category_id=None), base_currency="INR", today=TODAY)
    assert issue is not None
    question = build_question(
        issue, draft(category_id=None), draft_index=0, draft_count=2, round_number=1,
        base_currency="INR", locale="en-IN", today=TODAY, category_options=[],
    )  # fmt: skip
    payload = question.model_dump(by_alias=True)
    assert payload["type"] == "clarification"
    assert payload["field"] == "category" and payload["inputKind"] == "single_select"
    assert payload["allowCustomInput"] and payload["allowSkip"]
    assert payload["message"] == "(1 of 2) Which category fits dinner?"
    assert payload["id"] == "q-d1a2b3c4-category-1"


def test_unverified_amount_becomes_a_confirmation() -> None:
    issue = first_issue(draft(amount_confirmed=False), base_currency="INR", today=TODAY)
    assert issue is not None
    question = build_question(
        issue, draft(amount_confirmed=False), draft_index=0, draft_count=1, round_number=0,
        base_currency="INR", locale="en-IN", today=TODAY, category_options=[],
    )  # fmt: skip
    assert question.type == "confirmation"
    assert question.message == "Just to confirm: was it ₹350.00 for dinner?"


# -- answers ------------------------------------------------------------------------------


class _NoCategories:
    async def match(self, *args: Any) -> None:
        return None


def applier() -> AnswerApplier:
    return AnswerApplier(_NoCategories(), user_id=uuid.uuid4(), today=TODAY, locale="en-IN")  # type: ignore[arg-type]


AMOUNT_Q = {"type": "clarification", "field": "amount", "inputKind": "amount"}
DATE_Q = {"type": "clarification", "field": "date", "inputKind": "date"}
CONFIRM_Q = {"type": "confirmation", "reason": "amount_unverified"}


async def test_free_text_amount_answer() -> None:
    outcome = await applier().from_text(AMOUNT_Q, "it was 1.5k", draft(amount=None))
    assert outcome.kind == "applied" and outcome.draft is not None
    assert outcome.draft.amount == "1500" and outcome.draft.amount_confirmed


async def test_free_text_that_is_not_an_answer_is_routed_back_to_the_model() -> None:
    outcome = await applier().from_text(
        AMOUNT_Q, "how much did I spend this month?", draft(amount=None)
    )
    assert outcome.kind == "not_an_answer"


async def test_date_answers_reject_the_future() -> None:
    ok = await applier().apply_value("date", "last friday", draft(date=None))
    assert ok.kind == "applied" and ok.draft is not None and ok.draft.date == "2026-10-23"
    bad = await applier().apply_value("date", "2026-11-01", draft(date=None))
    assert bad.kind == "invalid"


async def test_confirmation_answers() -> None:
    yes = await applier().from_text(CONFIRM_Q, "yes", draft(amount_confirmed=False))
    assert yes.draft is not None and yes.draft.amount_confirmed
    corrected = await applier().from_text(
        CONFIRM_Q, "no, it was 400", draft(amount_confirmed=False)
    )
    assert (
        corrected.draft is not None
        and corrected.draft.amount == "400"
        and corrected.draft.amount_confirmed
    )
    no = await applier().from_text(CONFIRM_Q, "no", draft(amount_confirmed=False))
    assert no.draft is not None and no.draft.amount is None


async def test_cancel_and_option_validation() -> None:
    category_q = {"type": "clarification", "field": "category", "inputKind": "single_select",
                  "options": [{"value": "food"}], "allowCustomInput": False}  # fmt: skip
    assert (await applier().from_text(AMOUNT_Q, "never mind", draft())).kind == "cancel_all"
    tampered = await applier().from_response(
        category_q, {"action": "submit", "value": "rent"}, draft()
    )
    assert tampered.kind == "invalid"
    skip_not_allowed = await applier().from_response(AMOUNT_Q, {"action": "skip"}, draft())
    assert skip_not_allowed.kind == "invalid"


# -- replies --------------------------------------------------------------------------------


def test_free_form_replies_cannot_invent_figures() -> None:
    assert reply_is_grounded("Try “Spent ₹350 on dinner”.", "what can you do?")
    assert reply_is_grounded("Got it, 500 noted.", "is 500 a lot for dinner?")
    assert not reply_is_grounded("You spent ₹12,400 last month.", "hi")
    assert not reply_is_grounded("", "hi")


def test_period_phrase() -> None:
    assert period_phrase("This week") == "this week"
    assert period_phrase("Today") == "today"
    assert period_phrase("October 2026") == "October 2026"
