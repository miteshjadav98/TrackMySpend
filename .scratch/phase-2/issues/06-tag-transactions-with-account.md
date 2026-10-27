# 06: Tag transactions with an account

**What to build:** An expense or income can carry the account it was paid from or into. The
API accepts and returns it, the transactions page shows it on each row, filters by it, and
lets the user set or clear it in the edit dialog.

Spec: `../spec.md` → Implementation Decisions → Accounts (the transaction parts).

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] A new migration adds the optional account to transactions; existing rows stay valid; `alembic check` reports no drift.
- [ ] Create and update accept `accountId` (`null` clears it); the transaction view returns an `account` reference (id, name, kind) or null.
- [ ] Picking an archived account is 422 on `accountId`; an unknown or another user's account is 404.
- [ ] Editing other fields keeps an archived account already on the transaction.
- [ ] An expense may carry an account in another currency.
- [ ] The transaction list accepts an `accountId` filter.
- [ ] Audit snapshots include the account.
- [ ] The transactions page shows the account on rows that have one, offers an account filter, and the edit dialog has an account picker (active accounts, plus the current one if archived).
- [ ] Contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.
