/**
 * Shared API contract for MoneyMoney clients.
 *
 * `schema.d.ts` is generated from the FastAPI OpenAPI document (`npm run contracts` at the
 * repo root). The Python Pydantic models are the single source of truth; never edit the
 * generated file by hand. This module only adds readable aliases.
 */
import type { components, paths } from "./schema";

export type { components, paths };

type S = components["schemas"];

export type MeView = S["MeView"];
export type UserView = S["UserView"];
export type ProfileView = S["ProfileView"];
export type ProfileUpdate = S["ProfileUpdate"];
export type RegisterRequest = S["RegisterRequest"];
export type LoginRequest = S["LoginRequest"];
export type SessionView = S["SessionView"];
export type RevokedSessionsView = S["RevokedSessionsView"];
export type PasswordChange = S["PasswordChange"];
export type PasswordResetRequest = S["PasswordResetRequest"];
export type PasswordResetConfirm = S["PasswordResetConfirm"];

export type AccountView = S["AccountView"];
export type AccountCreate = S["AccountCreate"];
export type AccountUpdate = S["AccountUpdate"];
export type AccountKind = AccountView["kind"];

export type CategoryView = S["CategoryView"];
export type MoneyAmount = S["MoneyAmount"];
export type TransactionView = S["TransactionView"];
export type TransactionPage = S["TransactionPage"];
export type TransactionCreate = S["TransactionCreate"];
export type TransactionUpdate = S["TransactionUpdate"];
export type TransactionType = TransactionView["type"];
export type PaymentMethod = NonNullable<TransactionView["paymentMethod"]>;

export type MerchantRuleView = S["MerchantRuleView"];
export type MerchantRulePage = S["MerchantRulePage"];

export type SpendingSummary = S["SpendingSummary"];
export type CurrencySummary = S["CurrencySummary"];
export type CategoryTotal = S["CategoryTotal"];
export type PeriodView = S["PeriodView"];

export type ConversationView = S["ConversationView"];
export type ConversationPage = S["ConversationPage"];
export type ConversationDetail = S["ConversationDetail"];
export type MessageView = S["MessageView"];

export type ClarificationInteraction = S["ClarificationInteraction"];
export type ConfirmationInteraction = S["ConfirmationInteraction"];
export type TransactionsSavedInteraction = S["TransactionsSavedInteraction"];
export type SummaryInteraction = S["SummaryInteraction"];
export type TransactionListInteraction = S["TransactionListInteraction"];
export type SuggestionsInteraction = S["SuggestionsInteraction"];
export type SuggestedPrompt = S["SuggestedPrompt"];
export type DraftPreview = S["DraftPreview"];
export type InteractionOption = S["Option"];
export type Interaction = MessageView["ui"][number];
export type PendingInteraction = ClarificationInteraction | ConfirmationInteraction;
export type InteractionResponse = S["InteractionResponse"];

export type SendMessageRequest = S["SendMessageRequest"];
export type TurnResult = S["TurnResult"];
export type TurnEvent = S["TurnEvent"];

/** The error envelope every non-2xx response uses. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    requestId?: string | null;
    details?: Record<string, unknown> | null;
  };
}
