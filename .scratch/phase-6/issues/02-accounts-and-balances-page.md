# 02: Accounts and balances page

**What to build:** Promote accounts from a Settings-only list to an authenticated Accounts page
that shows known balances, incomplete coverage, per-currency position and balance history while
retaining account management in Settings.

Spec: `../spec.md` → User stories → Known balances; API and contract → Accounts; Testing and
release gates.

**Blocked by:** 01

**Status:** done on `phase-6/t02-accounts-page`

- [x] `/accounts` appears in desktop/mobile authenticated navigation and supports loading, error,
  empty and retry states.
- [x] Each account labels its asset/liability kind, formatted known balance or explicit unknown
  state, anchor date and archive state; credit balances/overdrafts are worded unambiguously.
- [x] Currency sections show known assets, liabilities and net position separately, name/count
  unknown exclusions and never combine currencies.
- [x] A user can set or correct an anchor amount/date with confirmation and see the audited result;
  invalid precision/dates are rejected and signed overdraft/credit anchors use explicit copy.
- [x] Account detail shows the typed, paginated balance ledger and links to the matching transaction
  source where one exists.
- [x] Existing Settings account create/rename/kind/archive behavior remains compatible, including
  old accounts with no anchor.
- [x] Browser tests cover mobile/dark mode, unknown/known/negative states, several currencies,
  history navigation and another user's inaccessible account.
- [x] Web typecheck/lint, production build and focused backend/browser tests pass.

## Comments

This page is a known-balance view, not a claim of complete net worth. The copy must preserve that
distinction when any account is unknown.

Verification passed with 20 focused API tests, 30 browser tests, web typecheck and lint, and a
webpack production build. Turbopack could not bind its CSS worker port in the local environment.
