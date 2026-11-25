"""What the accounts API accepts and returns."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field

from finance_core.money import MAX_AMOUNT_MINOR
from finance_core.schemas import ApiInput, ApiModel, MoneyAmount

AccountKindField = Literal["bank", "credit_card", "wallet", "cash", "other", "loan"]


class BalanceAnchor(ApiInput):
    """Start-of-day balance in account currency minor units. Negative means overdraft or credit."""

    as_of: date
    amount_minor: int = Field(strict=True, ge=-MAX_AMOUNT_MINOR, le=MAX_AMOUNT_MINOR)


class AccountView(ApiModel):
    """An account as clients see it. An archived account stays on past transactions."""

    id: uuid.UUID
    name: str
    kind: AccountKindField
    currency: str
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class AccountRef(ApiModel):
    """A compact reference to an account, as transactions show it."""

    id: uuid.UUID
    name: str
    kind: AccountKindField


class AccountBalanceView(AccountView):
    balance_anchor: BalanceAnchor | None
    balance: MoneyAmount | None
    balance_state: Literal[
        "held", "owed", "overdraft", "credit", "missing_anchor", "currency_mismatch"
    ]


class CurrencyPosition(ApiModel):
    currency: str
    assets: MoneyAmount
    liabilities: MoneyAmount
    net: MoneyAmount
    excluded_accounts: list[AccountRef]


class AccountOverview(ApiModel):
    accounts: list[AccountBalanceView]
    positions: list[CurrencyPosition]


class BalanceMovement(ApiModel):
    source_kind: Literal["transaction", "shared_expense", "settlement"]
    source_id: uuid.UUID
    occurred_on: date
    cash_effect: MoneyAmount
    balance_after: MoneyAmount | None


class BalanceLedger(ApiModel):
    items: list[BalanceMovement]
    next_offset: int | None


class AccountCreate(ApiInput):
    """A new account. Without a currency it takes the user's base currency."""

    name: str = Field(min_length=1, max_length=60)
    kind: AccountKindField
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    balance_anchor: BalanceAnchor | None = None


class AccountUpdate(ApiInput):
    """Omitted fields retain their values. An explicit null balanceAnchor clears the anchor.

    Setting or clearing balanceAnchor requires the account's last observed updatedAt in
    expectedUpdatedAt.

    There is no `currency`: an account's currency is fixed when it is created, so sending
    one is rejected like any other unknown field.
    """

    name: str | None = Field(default=None, min_length=1, max_length=60)
    kind: AccountKindField | None = None
    is_archived: bool | None = None
    balance_anchor: BalanceAnchor | None = None
    expected_updated_at: datetime | None = None
