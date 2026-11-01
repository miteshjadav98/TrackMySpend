"""What the friends API accepts and returns."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import EmailStr, Field

from finance_core.accounts.schemas import AccountRef
from finance_core.schemas import ApiInput, ApiModel

InviteStatusField = Literal["pending", "declined"]


class BalanceView(ApiModel):
    """What is owed between the user and a friend in one currency. Positive means the friend
    owes the user; negative means the user owes the friend. `formatted` is the size of the
    balance without a sign. Settled-up currencies are left out."""

    currency: str
    amount_minor: int
    amount: Decimal
    formatted: str


class FriendView(ApiModel):
    """A friend as clients see them. `invite_status` is set while an invite is waiting for an
    answer or was declined; a linked friend has none. `balances` has one entry per currency
    that is not settled up."""

    id: uuid.UUID
    name: str
    email: str | None
    is_linked: bool
    invite_status: InviteStatusField | None
    balances: list[BalanceView]
    created_at: datetime
    updated_at: datetime


class FriendCreate(ApiInput):
    """A new friend. With an email, an invite goes to whoever owns that email."""

    name: str = Field(min_length=1, max_length=80)
    email: EmailStr | None = None


class FriendUpdate(ApiInput):
    """Partial update. A name left out stays; an email sent as null is cleared."""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    email: EmailStr | None = None


class FriendInviteView(ApiModel):
    """An invite waiting for the signed-in user to accept or decline."""

    id: uuid.UUID
    from_name: str
    from_email: str
    created_at: datetime


SplitKindField = Literal["equal", "exact"]


class ParticipantInput(ApiInput):
    """One person in a shared expense. A null `friend_id` is the user themselves. The amount is
    given only for an exact split."""

    friend_id: uuid.UUID | None = None
    amount: Decimal | None = Field(default=None, gt=0, max_digits=18)


class SharedExpenseWrite(ApiInput):
    """The recorder's side of a shared expense: the bill, who paid, and how it is split.

    The recorder must be one of the participants. A null `payer_friend_id` means the user
    paid; when a friend paid, only the user and that friend may take part.
    """

    total: Decimal = Field(gt=0, max_digits=18)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    occurred_on: date | None = None
    description: str | None = Field(default=None, max_length=500)
    merchant: str | None = Field(default=None, max_length=200)
    payer_friend_id: uuid.UUID | None = None
    split: SplitKindField = "equal"
    participants: list[ParticipantInput] = Field(max_length=20)


class SharedExpenseCreate(SharedExpenseWrite):
    """A new shared expense. Category and account tag the user's own share."""

    category_id: uuid.UUID | None = None
    account_id: uuid.UUID | None = None


class SharedExpenseUpdate(SharedExpenseWrite):
    """A full replacement of the bill and split. The user's own category and account are
    changed on their share transaction, not here."""


class PersonView(ApiModel):
    """Someone in a shared expense, named the way the recorder knows them."""

    friend_id: uuid.UUID | None
    name: str
    is_you: bool


class ShareView(PersonView):
    """One participant's share."""

    amount: Decimal
    amount_minor: int
    amount_formatted: str


class SharedExpenseView(ApiModel):
    """A shared expense: the total, the payer and every share."""

    id: uuid.UUID
    total: Decimal
    total_minor: int
    currency: str
    total_formatted: str
    occurred_on: date
    description: str | None
    merchant: str | None
    payer: PersonView
    paid_by_you: bool
    shares: list[ShareView]
    # The user's own share as an ordinary expense transaction in their records.
    my_transaction_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


SettlementDirectionField = Literal["friend_paid_you", "you_paid_friend"]


class SettlementCreate(ApiInput):
    """Money that changed hands between the user and one friend, in either direction."""

    friend_id: uuid.UUID
    direction: SettlementDirectionField
    amount: Decimal = Field(gt=0, max_digits=18)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    occurred_on: date | None = None
    # The user's own account the money went into or came out of.
    account_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=500)


class SettlementFriend(ApiModel):
    """The friend a settlement is with, named as the user knows them."""

    id: uuid.UUID
    name: str


class SettlementView(ApiModel):
    """A settlement as its recorder sees it."""

    id: uuid.UUID
    friend: SettlementFriend
    direction: SettlementDirectionField
    amount: Decimal
    amount_minor: int
    currency: str
    amount_formatted: str
    occurred_on: date
    note: str | None
    account: AccountRef | None
    created_at: datetime


class SettlementCreated(SettlementView):
    """The reply to recording a settlement. `exceeds_balance` is true when it was more than
    was owed in that direction, so the balance now points the other way; `warning` says so."""

    exceeds_balance: bool
    warning: str | None


class HistoryEntry(ApiModel):
    """One line in a friend's history. `effect_minor` is how it moved the balance: positive
    means the friend owes the user more, negative means less."""

    kind: Literal["shared_expense", "settlement"]
    id: uuid.UUID
    occurred_on: date
    label: str | None
    currency: str
    effect_minor: int
    effect_formatted: str


class FriendDetail(ApiModel):
    """A friend with their balances and every shared expense and settlement between you."""

    friend: FriendView
    history: list[HistoryEntry]


class NoticeView(ApiModel):
    """One "Shared with you" notice, worded for the reader. `friend_id` is the reader's own
    friend row for the person behind it, so clients can link to that friend; null when the
    reader has no such row yet (a pending invite)."""

    id: uuid.UUID
    kind: str
    message: str
    friend_id: uuid.UUID | None
    is_read: bool
    created_at: datetime


class NoticeList(ApiModel):
    """The latest notices and the number still unread (which may exceed what is listed)."""

    unread_count: int
    items: list[NoticeView]


class NoticesRead(ApiInput):
    """Which notices to mark read; leave `ids` out to mark every unread one."""

    ids: list[uuid.UUID] | None = None


class UnreadCount(ApiModel):
    """How many notices are still unread."""

    unread_count: int
