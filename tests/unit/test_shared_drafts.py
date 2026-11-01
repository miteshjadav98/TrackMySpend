"""Shared-expense drafts: who is sharing, and what is still missing, with no model or database."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from finance_core.llm.schemas import ExtractedShare, ExtractedTransaction
from finance_core.workflows.drafts import (
    DraftPerson,
    TransactionDraft,
    draft_from_extraction,
    first_issue,
)

TODAY = date(2026, 10, 24)


def extract(**fields: Any) -> TransactionDraft:
    base: dict[str, Any] = {"type": "expense", "amount": "1000", "description": "Pizza"}
    return draft_from_extraction(
        ExtractedTransaction(**{**base, **fields}),
        draft_id="d-1",
        origin_message_id="m-1",
        source_text="1000 pizza with Jaymin",
        today=TODAY,
        locale="en-IN",
    )


def ready(draft: TransactionDraft, **changes: Any) -> TransactionDraft:
    """The draft with a category and every friend resolved, so only the sharing can be missing."""
    people = [
        p.model_copy(update={"friend_id": str(uuid.uuid4()), "name": p.said}) for p in draft.people
    ]
    return draft.model_copy(update={"category_id": "c", "people": people, **changes})


def issue(draft: TransactionDraft) -> tuple[str, str] | None:
    found = first_issue(draft, base_currency="INR", today=TODAY)
    return (found.field, found.reason) if found else None


def shares(me: str, jaymin: str) -> list[ExtractedShare]:
    return [
        ExtractedShare(person="me", amount=me),
        ExtractedShare(person="Jaymin", amount=jaymin),
    ]


def test_friends_named_in_an_extraction_become_people_to_resolve() -> None:
    draft = extract(participants=["Jaymin", "Riya"])
    assert [p.said for p in draft.people] == ["Jaymin", "Riya"]
    assert draft.split == "equal" and draft.payer_is_friend() is False


def test_the_payer_is_marked_among_the_people() -> None:
    draft = extract(participants=["Jaymin"], payer="jaymin")
    assert draft.people[0].paid and draft.payer_is_friend()


def test_a_payer_the_model_forgot_to_list_is_added_as_a_participant() -> None:
    draft = extract(participants=["Riya"], payer="Jaymin")
    assert [p.said for p in draft.people] == ["Riya", "Jaymin"]
    assert draft.people[1].paid


def test_exact_amounts_attach_to_the_user_and_to_each_friend() -> None:
    draft = extract(participants=["Jaymin"], split="exact", shares=shares("400", "600"))
    assert (draft.split, draft.my_amount, draft.people[0].amount) == ("exact", "400", "600")


def test_sharing_makes_an_untyped_draft_an_expense() -> None:
    assert extract(type=None, participants=["Jaymin"]).type == "expense"


def test_an_income_with_friends_named_is_not_shared() -> None:
    assert not extract(type="income", participants=["Jaymin"]).is_shared()


def test_an_unresolved_friend_is_asked_about_before_anything_else_shared() -> None:
    draft = extract(participants=["Jaymin"]).model_copy(update={"category_id": "c"})
    assert issue(draft) == ("friend", "unknown")


def test_a_name_matching_two_friends_is_asked_as_ambiguous() -> None:
    person = DraftPerson(said="Jaymin", ambiguous=True)
    draft = extract(participants=["Jaymin"]).model_copy(
        update={"category_id": "c", "people": [person]}
    )
    assert issue(draft) == ("friend", "ambiguous")


def test_a_friend_added_by_name_needs_no_further_question() -> None:
    person = DraftPerson(said="Jaymin", name="Jaymin", is_new=True)
    draft = extract(participants=["Jaymin"]).model_copy(
        update={"category_id": "c", "people": [person]}
    )
    assert issue(draft) is None


def test_a_friend_who_paid_cannot_share_with_two_others() -> None:
    draft = ready(extract(participants=["Jaymin", "Riya"], payer="Jaymin"))
    assert issue(draft) == ("payer", "too_many")


def test_a_friend_who_paid_can_share_with_the_user_alone() -> None:
    assert issue(ready(extract(participants=["Jaymin"], payer="Jaymin"))) is None


def test_exact_amounts_that_do_not_add_up_ask_again() -> None:
    draft = ready(extract(participants=["Jaymin"], split="exact", shares=shares("400", "500")))
    assert issue(draft) == ("split", "mismatch")


def test_exact_amounts_that_add_up_are_complete() -> None:
    draft = ready(extract(participants=["Jaymin"], split="exact", shares=shares("400", "600")))
    assert issue(draft) is None


def test_an_exact_split_missing_someones_amount_asks_for_it() -> None:
    draft = ready(extract(participants=["Jaymin"], split="exact", shares=[]))
    assert issue(draft) == ("split", "missing")


def test_an_equal_split_needs_no_amounts() -> None:
    assert issue(ready(extract(participants=["Jaymin", "Riya"]))) is None


def test_an_expense_with_no_friends_is_not_shared() -> None:
    draft = extract()
    assert not draft.is_shared()
    assert issue(draft.model_copy(update={"category_id": "c"})) is None
