# 01: Account balance foundation

**What to build:** Add dated balance anchors, asset/liability account semantics, loan accounts and
the deterministic cash-effect read model. Preserve the distinct reporting-share and cash-balance
meanings of shared expenses.

Spec: `../spec.md` → Domain model and invariants → Accounts and balances; API and contract →
Accounts; Scale, failure and operations plan.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] ADR 0003, the glossary, schemas and code use the same meanings for asset account, liability
  account, account balance, balance anchor and friend balance.
- [ ] Account kind supports `loan`; create/update/view supports an optional signed anchor amount and
  local date, with explicit held/owed/overdraft/credit meaning, without changing the fixed currency
  or weakening active-name uniqueness.
- [ ] Cross-boundary asset/liability kind changes cannot reinterpret an existing anchor; card bills
  and debt plans prevent incompatible kind changes.
- [ ] Accounts without anchors return an explicit unknown balance; no service or UI formats unknown
  as zero.
- [ ] `AccountBalanceService` applies exact integer cash effects on/after the anchor date for
  income, expense, both transfer ends, imports, settlements and shared expenses; liability
  direction is the inverse of an asset's money-in/money-out direction.
- [ ] A payer's shared-expense account reflects the full cash outflow exactly once; a non-payer's
  share has no purchase-time account effect; report/share totals remain unchanged.
- [ ] Edits, delete/restore, import undo and shared-expense/settlement changes produce the correct
  current result and invalidate the existing user data generation.
- [ ] Per-currency known asset/liability/net totals name unknown excluded accounts and never combine
  currencies.
- [ ] A paginated account balance ledger exposes typed source references and running effects without
  leaking another user or duplicating sensitive descriptions.
- [ ] Migration, integration/unit tests, contracts, API checks and Alembic drift checks pass.

## Comments

Planning decision: start-of-day anchors make same-day inclusion deterministic. Revisit monthly
checkpoints only after measuring 100,000 movements for one account.
