# 02: Shared expenses on the transactions page

**What to build:** A user records a shared expense from the transactions page: total, currency,
date, description, optional merchant, category, optional account, the payer (you or one
friend), and an equal or exact split among themselves and their friends. Only the user's share
is saved as an expense in their records, so summaries and category totals count the share. The
transaction list marks shared expenses, and opening one shows the total, payer and every share.
The recorder can edit or delete it.

Spec: `../spec.md` → User Stories 12-21, 24-28, 45, 47; Implementation Decisions → Model, Visibility.
ADR: `docs/adr/0001-shares-are-each-users-own-expense.md`.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Alembic revision for shared expenses and shares, plus a nullable shared-expense link on transactions, chained on the single head.
- [ ] Split arithmetic as pure functions with unit tests: an equal split gives each share the floor and the payer's share the leftover minor units; exact amounts must sum to the total, otherwise a validation error.
- [ ] When a friend is the payer, only the user and that friend may be participants (validation error otherwise).
- [ ] API: create, read, update, delete and list shared expenses. Creating saves the shared expense, the shares and the recorder's share transaction in one database transaction with audit events.
- [ ] The recorder's share transaction is an ordinary expense with the share amount; its amount, currency, date and type are read-only through the transaction endpoints (a clear error), while category, account and notes stay editable.
- [ ] Editing a shared expense updates its shares and the recorder's share transaction together; deleting removes both.
- [ ] Summaries and category totals count the user's share, not the total (integration test with a 1000 split two ways shows 500).
- [ ] Removing a friend who is in any shared expense archives them instead of deleting; archived friends cannot be added to new shared expenses.
- [ ] Shared-expense creation teaches the merchant rule from the recorder's category, like other saves.
- [ ] Web: a "Split" option in the add-transaction flow (friends picker, payer, equal or exact amounts with a live check that they add up), a shared marker on transaction rows, and a shared-expense detail view with edit and delete for the recorder.
- [ ] `npm run contracts` committed; API checks, full pytest, and web typecheck, lint and build pass.

## Comments
