"""Category precedence for a chat draft: picked > named > merchant rule > model's guess > ask."""

from __future__ import annotations

from datetime import date

from finance_core.llm.schemas import ExtractedTransaction
from finance_core.workflows.category_choice import CategoryOption, choose_category
from finance_core.workflows.drafts import draft_from_extraction

FOOD = CategoryOption(id="c-food", name="Food & Dining")
GROCERIES = CategoryOption(id="c-groceries", name="Groceries")
OFFICE_MEALS = CategoryOption(id="c-office", name="Office meals")


def test_a_category_picked_in_a_clarification_beats_everything() -> None:
    choice = choose_category(
        "swiggy 400 groceries", picked=FOOD, suggested=GROCERIES, merchant_rule=OFFICE_MEALS
    )
    assert choice is not None
    assert (choice.category, choice.source) == (FOOD, "picked")


def test_a_category_named_in_the_message_beats_the_merchant_rule() -> None:
    choice = choose_category(
        "swiggy 400 groceries", picked=None, suggested=GROCERIES, merchant_rule=OFFICE_MEALS
    )
    assert choice is not None
    assert (choice.category, choice.source) == (GROCERIES, "named")


def test_the_merchant_rule_beats_the_models_guess() -> None:
    choice = choose_category("swiggy 250", picked=None, suggested=FOOD, merchant_rule=OFFICE_MEALS)
    assert choice is not None
    assert (choice.category, choice.source) == (OFFICE_MEALS, "merchant_rule")


def test_the_models_guess_files_a_merchant_without_a_rule() -> None:
    choice = choose_category("swiggy 300", picked=None, suggested=FOOD, merchant_rule=None)
    assert choice is not None
    assert (choice.category, choice.source) == (FOOD, "model")


def test_with_nothing_to_go_on_the_user_is_asked() -> None:
    assert choose_category("spent 500", picked=None, suggested=None, merchant_rule=None) is None


# -- what counts as naming a category ----------------------------------------------------


def test_a_distinctive_word_of_the_name_counts_as_naming_it() -> None:
    choice = choose_category(
        "Swiggy 300 food", picked=None, suggested=FOOD, merchant_rule=OFFICE_MEALS
    )
    assert choice is not None
    assert (choice.category, choice.source) == (FOOD, "named")


def test_part_of_a_word_does_not_count_as_naming_it() -> None:
    choice = choose_category(
        "swiggy 300 seafood", picked=None, suggested=FOOD, merchant_rule=OFFICE_MEALS
    )
    assert choice is not None and choice.source == "merchant_rule"


def test_a_fallback_category_never_counts_as_named() -> None:
    other = CategoryOption(id="c-other", name="Other", is_fallback=True)
    choice = choose_category(
        "swiggy 300 other stuff", picked=None, suggested=other, merchant_rule=OFFICE_MEALS
    )
    assert choice is not None
    assert (choice.category, choice.source) == (OFFICE_MEALS, "merchant_rule")


def test_a_generic_word_of_the_name_does_not_count_as_naming_it() -> None:
    gifts_received = CategoryOption(id="c-gifts", name="Gifts Received")
    business = CategoryOption(id="c-business", name="Business & Freelance")
    choice = choose_category(
        "received 5000 from Amit", picked=None, suggested=gifts_received, merchant_rule=business
    )
    assert choice is not None
    assert (choice.category, choice.source) == (business, "merchant_rule")


# -- review fixes: what the message says about this item ---------------------------------

GYM = CategoryOption(id="c-gym", name="Gym")
HEALTH = CategoryOption(id="c-health", name="Health & Fitness")


def test_a_merchant_name_containing_a_category_word_keeps_its_rule() -> None:
    choice = choose_category(
        "cult fitness 1500",
        picked=None,
        suggested=HEALTH,
        merchant_rule=GYM,
        merchant="Cult Fitness",
    )
    assert choice is not None
    assert (choice.category, choice.source) == (GYM, "merchant_rule")


def test_a_category_word_beside_the_merchant_name_still_counts_as_named() -> None:
    choice = choose_category(
        "cult fitness 1500 fitness",
        picked=None,
        suggested=HEALTH,
        merchant_rule=GYM,
        merchant="Cult Fitness",
    )
    assert choice is not None and choice.source == "named"


def test_a_category_named_for_one_item_does_not_override_another_items_rule() -> None:
    extracted = ExtractedTransaction(type="expense", amount="300", merchant="Swiggy")
    swiggy = draft_from_extraction(
        extracted,
        draft_id="d1",
        origin_message_id="m1",
        source_text="swiggy 300 and dinner food 400",
        today=date(2026, 10, 24),
        locale="en-IN",
    )
    choice = choose_category(
        swiggy.item_text, picked=None, suggested=FOOD, merchant_rule=OFFICE_MEALS
    )
    assert swiggy.item_text == "swiggy 300"
    assert choice is not None and choice.source == "merchant_rule"


def test_a_plural_or_singular_form_counts_as_naming_a_category() -> None:
    choice = choose_category(
        "blinkit grocery 500", picked=None, suggested=GROCERIES, merchant_rule=OFFICE_MEALS
    )
    assert choice is not None and choice.source == "named"


def test_a_category_in_y_is_named_by_its_plural() -> None:
    entertainment = CategoryOption(id="c-ent", name="Hobby")
    choice = choose_category(
        "bought 5 hobbies 500", picked=None, suggested=entertainment, merchant_rule=OFFICE_MEALS
    )
    assert choice is not None and choice.source == "named"
