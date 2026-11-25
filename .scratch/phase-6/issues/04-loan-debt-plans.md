# 04: Loan debt plans

**What to build:** Add simple loan obligations on top of liability accounts: lender, installment,
cadence and next due date, with borrowings and repayments represented by transfers.

Spec: `../spec.md` → Domain model and invariants → Debt plans; User stories → Bills and debt; API
and contract → Bills and plans.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A debt plan belongs one-to-one to the user's loan account and supports lender, optional exact
  installment, cadence, next due date and note; non-loan and cross-user accounts are rejected.
- [ ] Borrowing from a loan account to an asset increases amount owed; repayment from an asset into
  the loan decreases it; both sides change atomically in the account balance engine.
- [ ] Accounts page shows amount owed, next due state and recent repayments without projecting
  interest or a payoff date.
- [ ] The user can advance, skip or change the next due date explicitly; no recurring transaction
  or interest entry is generated in the background.
- [ ] A new anchor from a lender statement reconciles interest/fees while preserving older history
  and the audit trail.
- [ ] Multi-currency and cross-currency transfers follow existing policy; a plan uses only its loan
  account currency.
- [ ] API writes are idempotent and integration tests cover create/update/delete, due transitions,
  borrowing, repayment, changed anchors, race conditions and user isolation.
- [ ] Contracts, API/web checks, browser tests and migration drift checks pass.

## Comments

This is deliberate simple debt tracking. Amortisation, principal/interest splits, penalties and
payoff advice stay out until a real lender contract model is specified.
