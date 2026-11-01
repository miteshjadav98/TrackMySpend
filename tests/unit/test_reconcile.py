"""Deterministic guards on top of the model's reading (failure modes seen in live evals)."""

from __future__ import annotations

from datetime import date

from finance_core.llm.schemas import ExtractedTransaction, SearchSpec, TurnUnderstanding
from finance_core.workflows.reconcile import reconcile

TODAY = date(2026, 10, 24)


def record(*transactions: ExtractedTransaction) -> TurnUnderstanding:
    return TurnUnderstanding(intent="record_transactions", transactions=list(transactions))


def test_split_transaction_fragments_are_merged() -> None:
    text = "paid 1,200 for electricity bill on 12 oct by credit card"
    result = reconcile(
        record(
            ExtractedTransaction(type="expense", amount="1200"),
            ExtractedTransaction(
                type="expense",
                category="utilities",
                date_text="12 oct",
                payment_method="credit_card",
            ),
        ),
        text,
        today=TODAY,
        locale="en-IN",
    )
    [tx] = result.transactions
    assert (tx.amount, tx.category, tx.payment_method, tx.date_text) == (
        "1200",
        "utilities",
        "credit_card",
        "12 oct",
    )


def test_described_fragments_that_only_fill_gaps_are_merged() -> None:
    result = reconcile(
        record(
            ExtractedTransaction(type="income", amount="50000"),
            ExtractedTransaction(category="salary", date_text="today", description="Salary"),
        ),
        "Got salary 50k today",
        today=TODAY,
        locale="en-IN",
    )
    [tx] = result.transactions
    assert (tx.amount, tx.category, tx.description) == ("50000", "salary", "Salary")


def test_duplicates_beyond_what_the_user_wrote_are_dropped() -> None:
    once = reconcile(
        record(
            ExtractedTransaction(amount="50000", type="income"),
            ExtractedTransaction(amount="50000", type="income"),
        ),
        "Got salary 50k today",
        today=TODAY,
        locale="en-IN",
    )
    assert len(once.transactions) == 1
    twice = reconcile(
        record(ExtractedTransaction(amount="200"), ExtractedTransaction(amount="200")),
        "lunch 200 and dinner 200",
        today=TODAY,
        locale="en-IN",
    )
    assert len(twice.transactions) == 2


def test_named_items_without_amounts_are_kept_for_a_question() -> None:
    result = reconcile(
        record(
            ExtractedTransaction(amount="200", description="Lunch"),
            ExtractedTransaction(description="Book"),
        ),
        "spent 200 on lunch and bought a book",
        today=TODAY,
        locale="en-IN",
    )
    assert [t.description for t in result.transactions] == ["Lunch", "Book"]


def test_gaps_are_filled_but_model_values_win() -> None:
    result = reconcile(
        record(ExtractedTransaction(type="expense", amount="845.50", category="shopping")),
        "bought groceries from Blinkit for 845.50 via gpay",
        today=TODAY,
        locale="en-IN",
    )
    [tx] = result.transactions
    assert tx.category == "shopping"  # the model's explicit choice is kept
    assert tx.payment_method == "upi"  # the gap is filled from the parser


def test_search_filters_are_completed() -> None:
    result = reconcile(
        TurnUnderstanding(intent="search_transactions", search=SearchSpec(type="expense")),
        "what was my biggest food expense",
        today=TODAY,
        locale="en-IN",
    )
    assert result.search is not None
    assert (result.search.category, result.search.sort) == ("food", "largest")


# -- transfers --------------------------------------------------------------------------


def test_a_transfer_the_model_left_without_accounts_gets_them_from_the_parser() -> None:
    result = reconcile(
        record(ExtractedTransaction(type="transfer", amount="5000")),
        "moved 5000 from HDFC to Paytm",
        today=TODAY,
        locale="en-IN",
    )
    [tx] = result.transactions
    assert (tx.account, tx.to_account) == ("HDFC", "Paytm")


def test_the_models_account_names_win_over_the_parser() -> None:
    result = reconcile(
        record(ExtractedTransaction(type="transfer", amount="5000", account="HDFC Savings")),
        "moved 5000 from HDFC to Paytm",
        today=TODAY,
        locale="en-IN",
    )
    [tx] = result.transactions
    assert (tx.account, tx.to_account) == ("HDFC Savings", "Paytm")


def test_a_transfer_never_gets_a_category_merchant_or_payment_method() -> None:
    result = reconcile(
        record(
            ExtractedTransaction(
                type="transfer", amount="15000", category="utilities", merchant="HDFC",
                payment_method="upi",
            )
        ),
        "paid 15000 credit card bill from HDFC",
        today=TODAY,
        locale="en-IN",
    )  # fmt: skip
    [tx] = result.transactions
    assert (tx.category, tx.merchant, tx.payment_method) == (None, None, None)
    assert (tx.account, tx.to_account) == ("HDFC", "Credit card")


def test_a_model_that_called_a_transfer_an_expense_is_corrected_by_the_parser() -> None:
    result = reconcile(
        record(ExtractedTransaction(type="expense", amount="2000", category="other")),
        "withdrew 2000 from SBI",
        today=TODAY,
        locale="en-IN",
    )
    [tx] = result.transactions
    assert (tx.type, tx.account, tx.to_account, tx.category) == ("transfer", "SBI", "Cash", None)


def test_a_search_for_transfers_wins_over_the_models_type() -> None:
    result = reconcile(
        TurnUnderstanding(intent="search_transactions", search=SearchSpec(type="expense")),
        "show my transfers this month",
        today=TODAY,
        locale="en-IN",
    )
    assert result.search is not None and result.search.type == "transfer"


def test_an_empty_model_transaction_is_filled_from_the_parser() -> None:
    result = reconcile(
        record(ExtractedTransaction()),
        "spent 250 on lunch",
        today=TODAY,
        locale="en-IN",
    )
    [tx] = result.transactions
    assert (tx.amount, tx.type) == ("250", "expense")
