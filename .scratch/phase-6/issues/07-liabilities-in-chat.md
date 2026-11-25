# 07: Balances, bills and debt in chat

**What to build:** Expose the new deterministic services through the existing typed workflow in all
three assistant languages, including card-payment allocation and voice-transcript parity.

Spec: `../spec.md` → User stories; Architecture → Request walkthrough; Testing and release gates.

**Blocked by:** 01, 03, 04, 05, 06

**Status:** ready-for-agent

- [ ] Typed intents cover account-balance queries, per-currency position, recording/updating a card
  bill, recording a loan/debt plan, borrowing, repayment and next-due queries.
- [ ] Existing transfer language such as “paid 15000 credit card bill from HDFC” remains a transfer
  and now allocates the payment to the correct oldest card bill after explicit confirmation.
- [ ] Workflow clarifications resolve missing/ambiguous account, amount, currency, statement/due
  date, lender and source account using user-scoped options; stale answers are rejected.
- [ ] Every write uses the domain service, existing turn replay/idempotency and one database
  transaction; the model never supplies a balance, allocation, status or computed due amount.
- [ ] Balance and obligation replies use fixed versioned interactions with exact server values and
  deep links to the Accounts page; unknown balance remains explicit.
- [ ] English, Hinglish and Gujarati typed cases produce equivalent structured outcomes and owned
  translated replies; a reviewed voice transcript produces exactly the same turn as typed text.
- [ ] Retry, disconnect, restart mid-question, provider/rules fallback, multiple same-name accounts,
  several currencies and another-user isolation are integration-tested.
- [ ] Existing transaction, transfer, friend, import, report and ordinary-summary behavior remains
  compatible; repeated live evaluation meets the release gates.
- [ ] Contracts, full backend/browser suites, API/web checks and production build pass.

## Comments

Do not add a separate voice workflow. The reviewed transcript is deliberately just another text
turn so replay, confirmation and recovery have one implementation.
