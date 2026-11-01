"""Transfers in chat, without a model or a database: parser phrasings, account names, and the
order in which a transfer draft asks for what is missing."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from finance_core.accounts.names import infer_account_kind, resolve_account_name
from finance_core.llm.rules import extract_search, extract_transactions
from finance_core.llm.schemas import ExtractedTransaction
from finance_core.workflows.drafts import TransactionDraft, draft_from_extraction, first_issue

TODAY = date(2026, 10, 24)


def account(name: str, kind: str = "bank") -> Any:
    return SimpleNamespace(name=name, kind=kind, id=name)


def parse(text: str) -> ExtractedTransaction:
    [tx] = extract_transactions(text, TODAY, "en-IN")
    return tx


# -- the offline parser ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "source", "target"),
    [
        ("moved 5000 from HDFC to Paytm", "HDFC", "Paytm"),
        ("transferred 2,500 from SBI to my ICICI account yesterday", "SBI", "ICICI"),
        ("transfer 1000 to Paytm from HDFC", "HDFC", "Paytm"),
        ("moved 700 from HDFC Savings into Paytm Wallet", "HDFC Savings", "Paytm Wallet"),
    ],
)
def test_parser_reads_both_ends_of_a_transfer(text: str, source: str, target: str) -> None:
    tx = parse(text)
    assert (tx.type, tx.account, tx.to_account) == ("transfer", source, target)
    assert tx.category is None and tx.merchant is None and tx.payment_method is None


def test_parser_reads_the_date_of_a_transfer() -> None:
    assert parse("moved 5000 from HDFC to Paytm yesterday").date == "2026-10-23"


def test_withdrawing_cash_moves_money_to_the_cash_account() -> None:
    tx = parse("withdrew 2000 from SBI")
    assert (tx.type, tx.account, tx.to_account) == ("transfer", "SBI", "Cash")


def test_paying_the_credit_card_bill_moves_money_to_the_credit_card() -> None:
    tx = parse("paid 15000 credit card bill from HDFC")
    assert (tx.type, tx.account, tx.to_account) == ("transfer", "HDFC", "Credit card")


def test_a_transfer_with_no_accounts_named_leaves_them_for_a_question() -> None:
    tx = parse("moved 5000")
    assert (tx.type, tx.account, tx.to_account) == ("transfer", None, None)


@pytest.mark.parametrize(
    "text", ["electricity bill 1200", "paid 800 for the phone bill", "lunch 180"]
)
def test_ordinary_bills_and_spending_stay_expenses(text: str) -> None:
    assert parse(text).type != "transfer"


def test_asking_for_transfers_searches_transfers() -> None:
    assert extract_search("show my transfers this month").type == "transfer"


# -- account names --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("Cash", "cash"),
        ("Wallet cash", "cash"),
        ("Amex Credit Card", "credit_card"),
        ("Axis Card", "credit_card"),
        ("Paytm", "wallet"),
        ("PhonePe", "wallet"),
        ("Axis Bank", "bank"),
        ("Axis Debit Card", "bank"),
        ("Zerodha", "bank"),
    ],
)
def test_a_new_accounts_kind_is_guessed_from_its_name(name: str, kind: str) -> None:
    assert infer_account_kind(name) == kind


def test_a_name_matches_an_account_ignoring_case_and_extra_words() -> None:
    accounts = [account("HDFC Savings"), account("Paytm Wallet", "wallet")]
    assert resolve_account_name("hdfc", accounts) is accounts[0]
    assert resolve_account_name("Paytm Wallet account", accounts) is accounts[1]


def test_a_name_that_fits_two_accounts_matches_none() -> None:
    accounts = [account("HDFC Savings"), account("HDFC Salary")]
    assert resolve_account_name("HDFC", accounts) is None


def test_an_unknown_name_matches_none() -> None:
    assert resolve_account_name("Kotak", [account("HDFC")]) is None


def test_a_bare_kind_means_the_only_account_of_that_kind() -> None:
    accounts = [account("Pocket", "cash"), account("HDFC Regalia", "credit_card")]
    assert resolve_account_name("cash", accounts) is accounts[0]
    assert resolve_account_name("Credit card", accounts) is accounts[1]


def test_a_bare_kind_with_two_such_accounts_matches_none() -> None:
    accounts = [account("Visa", "credit_card"), account("Amex", "credit_card")]
    assert resolve_account_name("credit card", accounts) is None


# -- what a transfer draft asks for, in order -----------------------------------------------


def transfer(**fields: Any) -> TransactionDraft:
    base: dict[str, Any] = {
        "id": "d1",
        "origin_message_id": "m1",
        "type": "transfer",
        "amount": "5000",
        "amount_confirmed": True,
        "date": "2026-10-24",
    }
    base.update(fields)
    return TransactionDraft(**base)


def issue(draft: TransactionDraft) -> tuple[str, str] | None:
    found = first_issue(draft, base_currency="INR", today=TODAY)
    return (found.field, found.reason) if found else None


def test_a_transfer_never_asks_for_a_category() -> None:
    full = transfer(account_id="a", to_account_id="b")
    assert issue(full) is None


def test_a_transfer_asks_for_the_source_before_the_target() -> None:
    assert issue(transfer()) == ("account", "missing")
    assert issue(transfer(account="Kotak")) == ("account", "unknown")
    assert issue(transfer(account_id="a")) == ("to_account", "missing")
    assert issue(transfer(account_id="a", to_account="Kotak")) == ("to_account", "unknown")


def test_a_typed_new_account_counts_as_answered() -> None:
    assert issue(transfer(account_id="a", to_account_new=True, to_account_name="Kotak")) is None


def test_the_same_account_at_both_ends_asks_again() -> None:
    assert issue(transfer(account_id="a", to_account_id="a")) == ("to_account", "same")
    typed = transfer(
        account_new=True, account_name="Kotak", to_account_new=True, to_account_name="kotak"
    )
    assert issue(typed) == ("to_account", "same")


def test_a_transfer_draft_drops_merchant_and_payment_method() -> None:
    draft = draft_from_extraction(
        ExtractedTransaction(
            type="transfer", amount="5000", merchant="HDFC", payment_method="upi",
            account="HDFC", to_account="Paytm",
        ),
        draft_id="d", origin_message_id="m", source_text="moved 5000 from HDFC to Paytm",
        today=TODAY, locale="en-IN",
    )  # fmt: skip
    assert (draft.merchant, draft.payment_method) == (None, None)
    assert (draft.account, draft.to_account) == ("HDFC", "Paytm")
