"""Expenses and income tagged with a named account, without a model or a database."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from finance_core.accounts.schemas import AccountRef
from finance_core.llm.rules import extract_transactions
from finance_core.llm.schemas import ExtractedTransaction, TurnUnderstanding
from finance_core.transactions.schemas import TransactionView
from finance_core.workflows.reconcile import reconcile
from finance_core.workflows.replies import compose_saved

TODAY = date(2026, 10, 24)
ACCOUNTS = ("HDFC", "Paytm", "SBI")


def parse(text: str) -> ExtractedTransaction:
    [tx] = extract_transactions(text, TODAY, "en-IN", account_names=ACCOUNTS)
    return tx


def record(tx: ExtractedTransaction) -> TurnUnderstanding:
    return TurnUnderstanding(intent="record_transactions", transactions=[tx])


# -- the offline parser ---------------------------------------------------------------------


def test_a_from_phrase_naming_an_account_is_the_account_not_the_merchant() -> None:
    tx = parse("paid 300 for lunch from HDFC")
    assert (tx.type, tx.account, tx.merchant) == ("expense", "HDFC", None)


def test_income_into_an_account_is_tagged_with_it() -> None:
    tx = parse("salary 50000 into HDFC")
    assert (tx.type, tx.account, tx.merchant) == ("income", "HDFC", None)


def test_a_from_phrase_naming_a_shop_stays_the_merchant() -> None:
    tx = parse("bought shoes 2000 from Nike")
    assert (tx.account, tx.merchant) == (None, "Nike")


def test_an_unknown_from_name_is_left_as_it_was() -> None:
    # Without the account list the parser cannot tell; it must not invent an account.
    [tx] = extract_transactions("paid 300 for lunch from HDFC", TODAY, "en-IN")
    assert tx.account is None


# -- reconcile, after the model's answer ----------------------------------------------------


def reconciled(tx: ExtractedTransaction, text: str) -> ExtractedTransaction:
    result = reconcile(record(tx), text, today=TODAY, locale="en-IN", account_names=ACCOUNTS)
    return result.transactions[0]


def test_a_merchant_that_is_really_the_account_the_model_named_is_dropped() -> None:
    tx = reconciled(
        ExtractedTransaction(type="expense", amount="300", account="HDFC", merchant="HDFC"),
        "paid 300 for lunch from HDFC",
    )
    assert (tx.account, tx.merchant) == ("HDFC", None)


def test_a_model_merchant_naming_an_account_after_from_becomes_the_account() -> None:
    tx = reconciled(
        ExtractedTransaction(type="expense", amount="300", merchant="HDFC"),
        "paid 300 for lunch from HDFC",
    )
    assert (tx.account, tx.merchant) == ("HDFC", None)


def test_a_merchant_that_only_looks_like_an_account_after_at_stays() -> None:
    tx = reconciled(
        ExtractedTransaction(type="expense", amount="300", merchant="SBI"),
        "paid 300 at SBI canteen",
    )
    assert (tx.account, tx.merchant) == (None, "SBI")


def test_an_unknown_account_the_model_named_is_not_a_merchant_either() -> None:
    tx = reconciled(
        ExtractedTransaction(type="expense", amount="300", account="Axis", merchant="Axis"),
        "paid 300 for lunch from Axis",
    )
    assert (tx.account, tx.merchant) == ("Axis", None)


# -- the slip -------------------------------------------------------------------------------


def saved(kind: str, account: str | None) -> dict:
    return TransactionView(
        id=uuid.uuid4(),
        type=kind,  # type: ignore[arg-type]
        amount=Decimal(300),
        amount_minor=30000,
        currency="INR",
        amount_formatted="₹300.00",
        occurred_on=TODAY,
        category=None,
        account=AccountRef(id=uuid.uuid4(), name=account, kind="bank") if account else None,
        description="lunch" if kind == "expense" else "salary",
        merchant=None,
        payment_method=None,
        notes=None,
        source="chat",
        version=1,
        created_at=datetime(2026, 10, 24, tzinfo=UTC),
        updated_at=datetime(2026, 10, 24, tzinfo=UTC),
    ).model_dump(mode="json", by_alias=True)


@pytest.mark.parametrize(("kind", "phrase"), [("expense", "from HDFC"), ("income", "into HDFC")])
def test_the_reply_says_which_account_a_tagged_transaction_used(kind: str, phrase: str) -> None:
    text, _ = compose_saved(
        [saved(kind, "HDFC")], today=TODAY, locale="en-IN", abandoned=False, interaction_id="x"
    )
    assert phrase in text


def test_the_reply_names_an_account_it_could_not_match() -> None:
    text, _ = compose_saved(
        [saved("expense", None)],
        today=TODAY,
        locale="en-IN",
        abandoned=False,
        interaction_id="x",
        unmatched_accounts=["Axis"],
    )
    assert "Axis" in text and "without an account" in text
