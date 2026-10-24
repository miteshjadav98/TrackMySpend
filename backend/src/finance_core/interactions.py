"""Typed UI contract between the assistant and the frontend.

The backend never sends HTML, JavaScript, or component code. It sends one of these
payloads; the frontend renders each `type` with an approved React component. Option lists
and labels are data-driven, but the set of component types is fixed and versioned.

Changing a payload shape is a breaking change for in-flight conversations (pending
interactions are stored in workflow checkpoints): add optional fields freely, and bump
`version` plus keep the old reader for anything else.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import Field

from finance_core.reports.schemas import PeriodView, SpendingSummary
from finance_core.schemas import ApiInput, ApiModel, MoneyAmount
from finance_core.transactions.schemas import TransactionView

INTERACTION_VERSION = 1

ClarifiableField = Literal[
    "type", "amount", "currency", "category", "date", "description", "payment_method"
]
InputKind = Literal["single_select", "multi_select", "text", "amount", "date"]


class Option(ApiModel):
    label: str = Field(max_length=80)
    value: str = Field(max_length=120)
    description: str | None = Field(default=None, max_length=160)
    icon: str | None = Field(default=None, max_length=32)


class SuggestedPrompt(ApiModel):
    label: str = Field(max_length=60)
    prompt: str = Field(max_length=200)
    # "send" submits the prompt as-is; "prefill" puts it in the composer to be finished
    # (used for "Add an expense" so a tap never records a made-up transaction).
    mode: Literal["send", "prefill"] = "send"
    icon: str | None = None


class DraftPreview(ApiModel):
    """What the assistant has understood so far, shown next to a question."""

    type: Literal["expense", "income"] | None = None
    amount: MoneyAmount | None = None
    category: str | None = None
    occurred_on: date | None = None
    occurred_on_label: str | None = None
    description: str | None = None
    merchant: str | None = None
    payment_method: str | None = None


class ClarificationInteraction(ApiModel):
    type: Literal["clarification"] = "clarification"
    id: str
    version: int = INTERACTION_VERSION
    message: str
    field: ClarifiableField
    input_kind: InputKind
    options: list[Option] = Field(default_factory=list)
    allow_custom_input: bool = False
    allow_skip: bool = False
    placeholder: str | None = None
    currency: str | None = None  # for amount inputs
    max_date: date | None = None  # for date inputs (no future dates)
    draft: DraftPreview | None = None
    draft_index: int = 0
    draft_count: int = 1


class ConfirmationInteraction(ApiModel):
    type: Literal["confirmation"] = "confirmation"
    id: str
    version: int = INTERACTION_VERSION
    message: str
    reason: Literal["amount_unverified", "possible_duplicate", "bulk_save"]
    confirm_label: str = "Save"
    cancel_label: str = "Cancel"
    drafts: list[DraftPreview] = Field(default_factory=list)
    destructive: bool = False


class TransactionsSavedInteraction(ApiModel):
    type: Literal["transactions_saved"] = "transactions_saved"
    id: str
    transactions: list[TransactionView]
    totals: list[MoneyAmount]  # one per currency


class SummaryInteraction(ApiModel):
    type: Literal["summary"] = "summary"
    id: str
    summary: SpendingSummary


class TransactionListInteraction(ApiModel):
    type: Literal["transaction_list"] = "transaction_list"
    id: str
    title: str
    period: PeriodView | None = None
    transactions: list[TransactionView]
    has_more: bool = False


class SuggestionsInteraction(ApiModel):
    type: Literal["suggestions"] = "suggestions"
    id: str
    prompts: list[SuggestedPrompt]


Interaction = Annotated[
    ClarificationInteraction
    | ConfirmationInteraction
    | TransactionsSavedInteraction
    | SummaryInteraction
    | TransactionListInteraction
    | SuggestionsInteraction,
    Field(discriminator="type"),
]

PendingInteraction = Annotated[
    ClarificationInteraction | ConfirmationInteraction, Field(discriminator="type")
]


class InteractionResponse(ApiInput):
    """The user's answer to a pending clarification or confirmation."""

    type: Literal["interaction_response"] = "interaction_response"
    interaction_id: str = Field(max_length=64)
    action: Literal["submit", "skip", "cancel"]
    value: (
        Annotated[str, Field(max_length=500)]
        | Annotated[list[Annotated[str, Field(max_length=120)]], Field(max_length=20)]
        | None
    ) = None

    def first_value(self) -> str | None:
        if isinstance(self.value, list):
            return self.value[0] if self.value else None
        return self.value


class TextInput(ApiInput):
    type: Literal["text"] = "text"
    text: str = Field(min_length=1, max_length=4000)


TurnInput = Annotated[TextInput | InteractionResponse, Field(discriminator="type")]
