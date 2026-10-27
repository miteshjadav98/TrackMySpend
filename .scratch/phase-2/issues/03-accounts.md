# 03: Accounts you can manage

**What to build:** A user can add, rename, re-kind, archive and unarchive their accounts
(bank, credit card, wallet, cash, other) through the API and in a new Settings → Accounts
section. Transactions don't use accounts yet (ticket 06).

Spec: `../spec.md` → Implementation Decisions → Accounts.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] A new migration adds the accounts table, with names unique per user (ignoring case) among active accounts; `alembic check` reports no drift.
- [ ] `GET /accounts`, `POST /accounts` and `PATCH /accounts/{id}` behave as the spec says, including the default currency (base currency) and a currency that cannot change after creation.
- [ ] A duplicate active name is 409 `account_exists`, also when unarchiving into a clash; more than 50 active accounts or an unsupported currency is 422; an unknown id is 404.
- [ ] Archived accounts are hidden by default and listed with `includeArchived=true`.
- [ ] Creating, updating, archiving and unarchiving each write an audit event.
- [ ] Another user's accounts are invisible and untouchable (isolation test, 404).
- [ ] Settings → Accounts lists accounts (name, kind, currency, archived state), adds one (name, kind, currency defaulting to the base currency), renames or re-kinds inline, archives and unarchives, and has a "show archived" toggle.
- [ ] The new domain module is in the import-linter contract; contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.
