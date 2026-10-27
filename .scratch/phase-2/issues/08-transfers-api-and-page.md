# 08: Transfers through the API and the transactions page

**What to build:** A user records a transfer between two of their accounts through the API,
sees it on the transactions page as "HDFC → Paytm Wallet" with neutral styling, filters by
it, and edits it. Transfers never change income, expense or category totals.

Spec: `../spec.md` → Implementation Decisions → Transfers (and the destination account under
Accounts).

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] A new migration adds the destination account and the check constraints (expense and income have none; a transfer has two different accounts and no category); existing rows stay valid; `alembic check` reports no drift.
- [ ] Creating a transfer is 201, and the view shows `account`, `toAccount` and no category.
- [ ] A missing account at either end, the same account twice, a category on a transfer, or a currency different from the accounts' currency is 422 with the field named.
- [ ] `toAccountId` on an expense or income is 422.
- [ ] Changing an expense into a transfer clears its category and requires both accounts; changing a transfer into an expense clears the destination account.
- [ ] A transfer leaves the summary, the category totals and the tally unchanged (checked against the reports API).
- [ ] The `accountId` filter matches either end of a transfer, and the type filter accepts `transfer`.
- [ ] A transfer never teaches or uses a merchant rule.
- [ ] The transactions page shows transfers as "From → To" with neutral amount styling, offers a Transfers type filter, and the edit dialog edits transfers (from and to pickers, no category).
- [ ] Contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.
