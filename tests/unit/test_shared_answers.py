"""The questions a shared expense asks and how a reply to each is applied, without a model."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from finance_core.friends.schemas import FriendView
from finance_core.llm.sharing import amounts_by_person
from finance_core.workflows.answers import AnswerApplier
from finance_core.workflows.drafts import DraftPerson, TransactionDraft, first_issue
from finance_core.workflows.questions import build_question

TODAY = date(2026, 10, 24)
NOW = datetime(2026, 10, 24, tzinfo=UTC)


def friend(name: str, email: str | None = None) -> FriendView:
    return FriendView(
        id=uuid.uuid4(), name=name, email=email, is_linked=False, invite_status=None, is_archived=False,
        balances=[],
        created_at=NOW, updated_at=NOW,
    )  # fmt: skip


JAYMIN_SHAH = friend("Jaymin Shah", "jaymin.shah@example.com")
JAYMIN_PATEL = friend("Jaymin Patel")
RIYA = friend("Riya")


def shared(*people: DraftPerson, **fields: Any) -> TransactionDraft:
    base: dict[str, Any] = {
        "id": "d1a2b3c4-0000", "origin_message_id": "m1", "type": "expense", "amount": "1000",
        "amount_confirmed": True, "category_id": "c", "category_name": "Food & Dining",
        "date": "2026-10-23", "description": "Pizza", "people": list(people),
    }  # fmt: skip
    return TransactionDraft(**{**base, **fields})


def jaymin(**fields: Any) -> DraftPerson:
    return DraftPerson(said="Jaymin", friend_id="1", name="Jaymin", **fields)


def applier(*friends: FriendView) -> AnswerApplier:
    return AnswerApplier(
        None,  # type: ignore[arg-type]
        user_id=uuid.uuid4(), today=TODAY, locale="en-IN", friends=friends,
    )  # fmt: skip


def ask(draft: TransactionDraft, *friends: FriendView) -> dict[str, Any]:
    issue = first_issue(draft, base_currency="INR", today=TODAY)
    assert issue is not None
    question = build_question(
        issue, draft, draft_index=0, draft_count=1, round_number=0, base_currency="INR",
        locale="en-IN", today=TODAY, category_options=[], friend_options=list(friends),
    )  # fmt: skip
    return question.model_dump(by_alias=True)


# -- questions ----------------------------------------------------------------------------


def test_an_unknown_name_asks_to_add_them_as_a_new_friend() -> None:
    question = ask(shared(DraftPerson(said="Jaymin")), RIYA)
    assert question["message"] == "Add Jaymin as a new friend?"
    assert question["field"] == "friend"
    assert question["options"][0] == {
        "label": "Yes, add Jaymin", "value": "add", "description": None, "icon": None,
    }  # fmt: skip


def test_an_ambiguous_name_offers_the_matching_friends_with_their_emails() -> None:
    question = ask(
        shared(DraftPerson(said="Jaymin", ambiguous=True)), JAYMIN_SHAH, JAYMIN_PATEL, RIYA
    )
    assert question["message"] == "Which Jaymin do you mean?"
    assert [(o["label"], o["description"]) for o in question["options"]] == [
        ("Jaymin Shah", "jaymin.shah@example.com"),
        ("Jaymin Patel", None),
    ]


def test_a_friend_who_paid_with_two_others_explains_the_limit() -> None:
    question = ask(shared(jaymin(paid=True), DraftPerson(said="Riya", friend_id="2", name="Riya")))
    assert question["field"] == "payer"
    assert "only be split between you and the friend who paid" in question["message"]
    assert [o["value"] for o in question["options"]] == ["i_paid", "only_payer"]


def test_exact_amounts_that_do_not_add_up_say_what_they_added_up_to() -> None:
    question = ask(shared(jaymin(amount="500"), split="exact", my_amount="400"))
    assert question["field"] == "split"
    assert question["message"].startswith("Those add up to ₹900.00, but the total is ₹1,000.00.")


# -- answers ------------------------------------------------------------------------------


async def test_agreeing_to_add_a_friend_keeps_the_name_for_save() -> None:
    outcome = await applier().apply_value("friend", "add", shared(DraftPerson(said="jaymin")))
    assert outcome.draft is not None
    person = outcome.draft.people[0]
    assert (person.is_new, person.name, person.friend_id) == (True, "Jaymin", None)


async def test_tapping_a_friend_resolves_the_name_to_that_friend() -> None:
    draft = shared(DraftPerson(said="Jaymin", ambiguous=True))
    outcome = await applier(JAYMIN_SHAH, JAYMIN_PATEL).apply_value(
        "friend", str(JAYMIN_PATEL.id), draft
    )
    assert outcome.draft is not None
    person = outcome.draft.people[0]
    assert (person.friend_id, person.name, person.ambiguous) == (
        str(JAYMIN_PATEL.id), "Jaymin Patel", False,
    )  # fmt: skip


async def test_typing_a_full_name_picks_the_matching_friend() -> None:
    draft = shared(DraftPerson(said="Jaymin", ambiguous=True))
    outcome = await applier(JAYMIN_SHAH, JAYMIN_PATEL).apply_value("friend", "jaymin shah", draft)
    assert outcome.draft is not None and outcome.draft.people[0].friend_id == str(JAYMIN_SHAH.id)


async def test_a_reply_that_is_neither_yes_nor_a_friend_is_not_accepted() -> None:
    draft = shared(DraftPerson(said="Jaymin"))
    outcome = await applier(RIYA).apply_value("friend", "maybe tomorrow", draft)
    assert outcome.kind == "invalid"


async def test_saying_i_paid_keeps_everyone_and_clears_the_friend_payer() -> None:
    draft = shared(jaymin(paid=True), DraftPerson(said="Riya", friend_id="2"))
    outcome = await applier().apply_value("payer", "i_paid", draft)
    assert outcome.draft is not None
    assert [p.said for p in outcome.draft.people] == ["Jaymin", "Riya"]
    assert not outcome.draft.payer_is_friend()


async def test_narrowing_to_the_payer_drops_the_other_friends() -> None:
    draft = shared(jaymin(paid=True), DraftPerson(said="Riya", friend_id="2"))
    outcome = await applier().apply_value("payer", "only_payer", draft)
    assert outcome.draft is not None
    assert [p.said for p in outcome.draft.people] == ["Jaymin"]


async def test_new_exact_amounts_replace_the_old_ones() -> None:
    draft = shared(jaymin(amount="500"), split="exact", my_amount="400")
    outcome = await applier().apply_value("split", "I had 400, Jaymin 600", draft)
    assert outcome.draft is not None
    assert (outcome.draft.my_amount, outcome.draft.people[0].amount) == ("400", "600")


async def test_asking_to_split_equally_drops_the_exact_amounts() -> None:
    draft = shared(jaymin(amount="500"), split="exact", my_amount="400")
    outcome = await applier().apply_value("split", "equal", draft)
    assert outcome.draft is not None
    assert (outcome.draft.split, outcome.draft.my_amount, outcome.draft.people[0].amount) == (
        "equal", None, None,
    )  # fmt: skip


async def test_a_reply_without_an_amount_for_everyone_is_not_accepted() -> None:
    draft = shared(jaymin(), split="exact")
    outcome = await applier().apply_value("split", "I had 400", draft)
    assert outcome.kind == "invalid"


# -- reading amounts ----------------------------------------------------------------------


def test_a_bare_list_of_amounts_is_read_in_order_the_user_first() -> None:
    assert amounts_by_person("400 600", ["Jaymin"]) == {"me": 400, "jaymin": 600}


def test_amounts_with_names_go_to_the_named_people() -> None:
    assert amounts_by_person("Jaymin 600, I had 400", ["Jaymin"]) == {"jaymin": 600, "me": 400}
