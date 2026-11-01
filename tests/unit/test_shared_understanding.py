"""How the offline parser reads shared-expense phrasings, and how reconcile treats them."""

from __future__ import annotations

from datetime import date

from finance_core.llm.rules import extract_transactions
from finance_core.llm.schemas import ExtractedShare, ExtractedTransaction, TurnUnderstanding
from finance_core.workflows.reconcile import reconcile

TODAY = date(2026, 10, 24)
FRIENDS = ("Jaymin", "Riya")


def parse(text: str, friends: tuple[str, ...] = FRIENDS) -> list[ExtractedTransaction]:
    return extract_transactions(text, TODAY, "en-IN", friend_names=friends)


def test_me_and_a_friend_spending_is_an_equal_shared_expense_paid_by_me() -> None:
    [tx] = parse("me and Jaymin spent 1000 on pizza, split it")
    assert (tx.type, tx.amount, tx.category, tx.description) == ("expense", "1000", "food", "Pizza")
    assert (tx.participants, tx.payer, tx.split, tx.shares) == (["Jaymin"], None, "equal", [])


def test_a_friend_paying_is_named_as_payer_and_as_a_participant() -> None:
    [tx] = parse("Jaymin paid 1000 for pizza, split it")
    assert (tx.amount, tx.participants, tx.payer, tx.split) == (
        "1000",
        ["Jaymin"],
        "Jaymin",
        "equal",
    )


def test_several_friends_are_all_participants() -> None:
    [tx] = parse("me, Jaymin and Riya spent 1500 on cab, split it")
    assert (tx.amount, tx.participants, tx.payer) == ("1500", ["Jaymin", "Riya"], None)
    assert tx.category == "transport"


def test_exact_amounts_say_what_each_person_had_and_the_total_stays_the_bill() -> None:
    [tx] = parse("dinner 1000 with Jaymin, I had 400 and he had 600")
    assert (tx.amount, tx.participants, tx.split) == ("1000", ["Jaymin"], "exact")
    assert tx.shares == [
        ExtractedShare(person="me", amount="400"),
        ExtractedShare(person="Jaymin", amount="600"),
    ]


def test_a_name_in_lower_case_is_tidied_to_a_name() -> None:
    [tx] = parse("me and jaymin spent 600 on lunch, split it", friends=())
    assert tx.participants == ["Jaymin"]


def test_split_with_friends_without_me_spending_words() -> None:
    [tx] = parse("split 900 on movie with Riya")
    assert (tx.amount, tx.participants, tx.split) == ("900", ["Riya"], "equal")


def test_a_plain_expense_with_a_friend_in_the_text_is_not_shared() -> None:
    [tx] = parse("coffee with Jaymin 200")
    assert (tx.amount, tx.participants) == ("200", [])


def test_a_friend_paying_without_a_split_is_not_shared() -> None:
    [tx] = parse("Jaymin paid 1000 for pizza")
    assert tx.participants == []


def test_generic_company_is_not_a_friend_name() -> None:
    [tx] = parse("me and my friends spent 2000 on dinner, split it")
    assert tx.participants == []


def test_paid_from_an_account_still_reads_as_before() -> None:
    [tx] = parse("me and Jaymin spent 1000 on pizza from HDFC, split it")
    assert tx.participants == ["Jaymin"]


def test_reconcile_fills_the_sharing_a_model_left_out() -> None:
    model = TurnUnderstanding(
        intent="record_transactions",
        transactions=[ExtractedTransaction(type="expense", amount="1000", description="Pizza")],
    )
    text = "me and Jaymin spent 1000 on pizza, split it"
    [tx] = reconcile(model, text, today=TODAY, locale="en-IN", friend_names=FRIENDS).transactions
    assert (tx.participants, tx.split) == (["Jaymin"], "equal")


def test_reconcile_never_files_a_participant_as_the_merchant() -> None:
    model = TurnUnderstanding(
        intent="record_transactions",
        transactions=[
            ExtractedTransaction(
                type="expense", amount="1000", merchant="Jaymin", participants=["Jaymin"]
            )
        ],
    )
    [tx] = reconcile(
        model, "me and Jaymin spent 1000 on pizza, split it", today=TODAY, locale="en-IN",
        friend_names=FRIENDS,
    ).transactions  # fmt: skip
    assert tx.merchant is None


def test_reconcile_keeps_what_the_model_read_over_the_parser() -> None:
    model = TurnUnderstanding(
        intent="record_transactions",
        transactions=[
            ExtractedTransaction(
                type="expense", amount="1000", participants=["Riya"], payer="Riya", split="equal"
            )
        ],
    )
    [tx] = reconcile(
        model, "me and Jaymin spent 1000 on pizza, split it", today=TODAY, locale="en-IN",
        friend_names=FRIENDS,
    ).transactions  # fmt: skip
    assert (tx.participants, tx.payer) == (["Riya"], "Riya")
