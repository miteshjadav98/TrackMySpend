# 02: Reports page, periods and currency selection

**What to build:** Add an authenticated Reports destination with reproducible URL filters, exact KPI
cards and useful loading/empty/error states. Multi-currency periods show one currency at a time.

Spec: `../spec.md` → User stories 1-7; Web contract.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `/reports` is linked from desktop and mobile navigation and restores period, custom dates and
  selected currency from the URL.
- [ ] Presets cover this month, last month, last 3 months, last 6 months, this year and last year,
  plus a bounded custom range with clear validation.
- [ ] KPI cards show spent, received and net for one selected currency, the exact inclusive dates,
  transaction count and comparison values without doing financial arithmetic in the browser.
- [ ] Base currency is first; additional currencies are explicit tabs/chips and are never combined.
- [ ] Loading, API failure, no transactions and no data for a selected currency each have a useful,
  accessible state; empty reports link to add/import transactions.
- [ ] Query keys and ledger invalidation refresh reports after every existing transaction/import/
  shared-expense mutation.
- [ ] Web typecheck, lint and production build pass; component/browser coverage checks URL restore,
  multi-currency selection, mobile layout and dark mode.

