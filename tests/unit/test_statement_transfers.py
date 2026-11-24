"""Transfer suggestions use names and payment narration without guessing across accounts."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from finance_core.accounts.schemas import AccountKindField, AccountView
from finance_core.imports.transfers import transfer_account_candidates


def account(
    name: str, kind: AccountKindField = "bank", *, currency: str = "INR", is_archived: bool = False
) -> AccountView:
    return AccountView(
        id=uuid4(), name=name, kind=kind, currency=currency, is_archived=is_archived,
        created_at=datetime(2026, 10, 1, tzinfo=UTC), updated_at=datetime(2026, 10, 1, tzinfo=UTC),
    )  # fmt: skip


@pytest.mark.parametrize("narration", ["NEFT TO HDFC-SAVINGS", "IMPS/HDFC/SELF/153"])
def test_statement_narration_can_name_an_account_with_phase_two_name_rules(narration: str) -> None:
    axis = account("Axis")
    hdfc = account("HDFC Savings")
    assert transfer_account_candidates(
        narration, direction="out", account=axis, accounts=[axis, hdfc]
    ) == [hdfc.id]


def test_card_payment_targets_the_only_matching_card_and_card_credit_targets_the_bank() -> None:
    hdfc = account("HDFC Savings")
    card = account("Rewards", "credit_card")
    other_cards = [
        account("US Visa", "credit_card", currency="USD"),
        account("Old card", "credit_card", is_archived=True),
    ]
    accounts = [hdfc, card, *other_cards]
    assert transfer_account_candidates(
        "CC PAYMENT", direction="out", account=hdfc, accounts=accounts
    ) == [card.id]
    assert transfer_account_candidates(
        "PAYMENT RECEIVED. THANK YOU", direction="in", account=card, accounts=accounts
    ) == [hdfc.id]
    fuel = account("Fuel", "credit_card")
    accounts.append(fuel)
    assert transfer_account_candidates(
        "CC PAYMENT", direction="out", account=hdfc, accounts=accounts
    ) == [card.id, fuel.id]


@pytest.mark.parametrize("narration", ["SELF", "TRANSFER TO OWN A/C"])
def test_self_transfer_needs_a_unique_other_account(narration: str) -> None:
    axis = account("Axis")
    hdfc = account("HDFC")
    wallet = account("Wallet", "wallet")
    assert transfer_account_candidates(
        narration, direction="out", account=axis, accounts=[axis, hdfc]
    ) == [hdfc.id]
    assert transfer_account_candidates(
        narration, direction="out", account=axis, accounts=[axis, hdfc, wallet]
    ) == [hdfc.id, wallet.id]


@pytest.mark.parametrize(
    "narration", ["UPI/SHOP/shop@hdfc", "NEFT/HDFC0000001/EMPLOYER", "DEBIT CARD PAYMENT"]
)
def test_payment_routing_details_do_not_name_the_users_other_account(narration: str) -> None:
    axis = account("Axis")
    hdfc = account("HDFC")
    card = account("Rewards", "credit_card")
    assert (
        transfer_account_candidates(
            narration, direction="out", account=axis, accounts=[axis, hdfc, card]
        )
        == []
    )
