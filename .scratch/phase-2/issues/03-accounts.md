# 03: Accounts you can manage

**What to build:** A user can add, rename, re-kind, archive and unarchive their accounts
(bank, credit card, wallet, cash, other) through the API and in a new Settings → Accounts
section. Transactions don't use accounts yet (ticket 06).

Spec: `../spec.md` → Implementation Decisions → Accounts.

**Blocked by:** 01

**Status:** done

- [x] A new migration adds the accounts table, with names unique per user (ignoring case) among active accounts; `alembic check` reports no drift.
- [x] `GET /accounts`, `POST /accounts` and `PATCH /accounts/{id}` behave as the spec says, including the default currency (base currency) and a currency that cannot change after creation.
- [x] A duplicate active name is 409 `account_exists`, also when unarchiving into a clash; more than 50 active accounts or an unsupported currency is 422; an unknown id is 404.
- [x] Archived accounts are hidden by default and listed with `includeArchived=true`.
- [x] Creating, updating, archiving and unarchiving each write an audit event.
- [x] Another user's accounts are invisible and untouchable (isolation test, 404).
- [x] Settings → Accounts lists accounts (name, kind, currency, archived state), adds one (name, kind, currency defaulting to the base currency), renames or re-kinds inline, archives and unarchives, and has a "show archived" toggle.
- [x] The new domain module is in the import-linter contract; contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.

## Comments

Merged to `phase-2/integration` from branch `phase-2/t03-accounts` (head `ec2193a`), in the commit "Merge ticket 03: accounts you can manage". The merge was clean; the migration is `0003_accounts` after `0002` and `alembic heads` prints one head. Every criterion is met and checked against the code and tests. Checks on the merge: `npm run check:api` clean, `uv run pytest` 203 passed and 1 skipped (the live eval), `alembic check` reports no drift, `npm run contracts` gives no content diff, `npm run check:web` and `npm run build:web` pass.

Decision: `GET /accounts` is unpaginated, unlike the spec's "keyset pagination for lists". A user has at most 50 active accounts, so the list is bounded, and the ticket 06 pickers need the full list.

At the merge, the Add account form was keyed by the base currency. The settings page stays alive (`<Activity>`) and the currency picker reads its default only when mounted, so a base-currency change made in Profile left the old currency as the default.

Follow-ups:

- The 50-active-account limit is a count check with no database backstop (unlike the unique name index), so two creates racing at 49 can both save. Lock the user's row or accept it.
