# 02: Reports page, periods and currency selection

**What to build:** Add an authenticated Reports destination with reproducible URL filters, exact KPI
cards and useful loading/empty/error states. Multi-currency periods show one currency at a time.

Spec: `../spec.md` → User stories 1-7; Web contract.

**Blocked by:** 01

**Status:** done

- [x] `/reports` is linked from desktop and mobile navigation and restores period, custom dates and
  selected currency from the URL.
- [x] Presets cover this month, last month, last 3 months, last 6 months, this year and last year,
  plus a bounded custom range with clear validation.
- [x] KPI cards show spent, received and net for one selected currency, the exact inclusive dates,
  transaction count and comparison values without doing financial arithmetic in the browser.
- [x] Base currency is first; additional currencies are explicit tabs/chips and are never combined.
- [x] Loading, API failure, no transactions and no data for a selected currency each have a useful,
  accessible state; empty reports link to add/import transactions.
- [x] Query keys and ledger invalidation refresh reports after every existing transaction/import/
  shared-expense mutation.
- [x] Web typecheck, lint and production build pass; component/browser coverage checks URL restore,
  multi-currency selection, mobile layout and dark mode.


## Comments

Merged `phase-5/t02-reports` at `7a49b73` into `phase-5/integration`; this tracker
update is included in that merge commit. Web typecheck, ESLint and production build passed;
12 production-browser tests and 5 reporting integration tests passed. Contracts had no drift.
Includes the expired-session redirect regression fix and Next.js 16.4.6 security integration.
