# 05: Transfers between the user's own accounts in statements

**What to build:** A statement row whose narration names one of the user's accounts, or reads like
a card bill or self transfer ("CC PAYMENT", "SELF", "TRANSFER TO OWN A/C"), is suggested in the
preview as a transfer to that account, which the user can accept, retarget or reject. When the
other account's statement is imported later, its matching row (same amount, opposite direction,
within 3 days) joins the existing transfer instead of being saved again.

Spec: `../spec.md` → User Stories 26-28; Implementation Decisions → Likely duplicates and transfers.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Pure transfer suggestion (account names via the Phase 2 account-name rules, plus card-bill and self-transfer patterns), with unit tests.
- [ ] The preview shows suggested transfers with the other account, and lets the user accept, pick another account, or turn the row back into an expense or income.
- [ ] Confirming saves accepted transfers as transfers (from this account to the other, or the reverse for money in), never as spending or income.
- [ ] A row that matches an existing transfer between the same two accounts with the same amount within 3 days is marked "already recorded as a transfer" and not saved again.
- [ ] Integration test: import the HDFC savings statement with a card payment, then the card statement; one transfer exists, summaries count no spending for it.
- [ ] API checks, full pytest, and web typecheck, lint and build pass.

## Comments
