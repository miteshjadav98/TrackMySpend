# 06: Tag transactions with an account

**What to build:** An expense or income can carry the account it was paid from or into. The
API accepts and returns it, the transactions page shows it on each row, filters by it, and
lets the user set or clear it in the edit dialog.

Spec: `../spec.md` → Implementation Decisions → Accounts (the transaction parts).

**Blocked by:** 03

**Status:** done

- [x] A new migration adds the optional account to transactions; existing rows stay valid; `alembic check` reports no drift.
- [x] Create and update accept `accountId` (`null` clears it); the transaction view returns an `account` reference (id, name, kind) or null.
- [x] Picking an archived account is 422 on `accountId`; an unknown or another user's account is 404.
- [x] Editing other fields keeps an archived account already on the transaction.
- [x] An expense may carry an account in another currency.
- [x] The transaction list accepts an `accountId` filter.
- [x] Audit snapshots include the account.
- [x] The transactions page shows the account on rows that have one, offers an account filter, and the edit dialog has an account picker (active accounts, plus the current one if archived).
- [x] Contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.

## Comments

Merged to `phase-2/integration` in the commit "Merge ticket 06: tag transactions with an account". All criteria met. The migration was renumbered to `0006_transaction_accounts` because ticket 07 took 0005.
