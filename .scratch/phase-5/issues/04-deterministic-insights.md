# 04: Deterministic insights with evidence

**What to build:** Produce and display a small set of typed, auditable facts: spending change,
largest expense category and largest merchant. These are rules over report values, not LLM prose or
financial advice.

Spec: `../spec.md` → User stories 13-16; Comparison and insights.

**Blocked by:** 01, 02

**Status:** done

- [x] Typed insight schemas cover spending change, largest category and largest merchant, with
  currency, period and structured supporting values.
- [x] Insights are omitted when prerequisites are absent; zero previous spending is described
  explicitly and never becomes Infinity/NaN or a misleading percentage.
- [x] Wording is deterministic, localized with the existing money/date formatters, and makes no
  forecast, anomaly, cause or recommendation claim.
- [x] Each category/merchant insight links to the same exact Transactions drill-down as its chart.
- [x] Unit tests assert rule boundaries, evidence and wording; integration tests prove values match
  the overview aggregates for single- and multi-currency users.
- [x] Reports page remains useful when there are no insight cards.
- [x] Contracts, API checks, full pytest and web checks pass.


## Comments

Integrated the verified implementation at `3642808`, including the separately committed
bulk-import fix `595aa32`. Verification: 779 backend tests passed, 2 opt-in live tests
skipped, 20 browser tests passed, API/web static checks and production build passed.
