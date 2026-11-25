# 03: Credit-card bills and payment allocation

**What to build:** Track credit-card statement obligations and allocate existing card-payment
transfers without creating duplicate expenses.

Spec: `../spec.md` → Domain model and invariants → Credit-card bills; API and contract → Bills and
plans; User stories → Bills and debt.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A user can create, view, update and delete a bill for their credit-card account with statement
  period/date, due date, total due and optional minimum due; currency comes from the card.
- [ ] Validation rejects another user's account, non-card accounts, invalid date order, overlapping
  periods, duplicate statement dates, precision errors and minimum due above total due.
- [ ] A transfer into the card can be allocated only up to its amount and only once in aggregate;
  payment and bill currencies/accounts must match.
- [ ] New card-payment transfers allocate FIFO by due date across unpaid bills; excess remains an
  unallocated card repayment and never becomes an expense.
- [ ] Transfer/bill edit, delete and restore recomputes allocations atomically and deterministically;
  users can correct an allocation explicitly.
- [ ] Open, partially paid, paid, overdue and minimum-due progress are computed from dates and exact
  allocations rather than stored mutable status flags.
- [ ] Accounts page shows upcoming/overdue bills and payment progress with no cross-currency total.
- [ ] Write requests are idempotent; audit, user isolation, race/locking and rollback cases are
  covered by real-Postgres integration tests.
- [ ] Contracts, API/web checks, browser tests and migration drift checks pass.

## Comments

Recording a bill is a liability reminder, not a ledger movement. Purchases already changed the card
amount owed; the payment transfer changes it again in the opposite direction.
