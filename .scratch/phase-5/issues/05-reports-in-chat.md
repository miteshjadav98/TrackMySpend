# 05: Charts and insights in chat

**What to build:** Explicit trend, breakdown and insight questions return one fixed report
interaction based on `ReportService`, with a deep link to the full Reports page. Existing compact
summary questions do not change.

Spec: `../spec.md` → User stories 17-19; Chat contract.

**Blocked by:** 01, 03, 04

**Status:** done

- [x] A versioned `report` interaction carries a bounded trusted report payload and reproducible
  Reports-page URL; old stored interactions continue to load.
- [x] Understanding distinguishes explicit trend/breakdown/insight requests from ordinary totals;
  the offline parser covers the same supported phrases.
- [x] Workflow nodes call `ReportService`; no model output supplies amounts, grouping, percentages,
  data points or currency conversion.
- [x] Chat renders an accessible compact report card and links to the full report with matching
  period/currency filters.
- [x] Unit/integration tests cover routing, replay, restart, one and multiple currencies, ordinary
  summary regression and equality with the reports API.
- [x] New prompt cases are added to the eval set and measured over repeated live runs before release.
- [x] Contracts, API checks, full pytest and web checks pass.


## Comments

2026-11-24: Merged as `9d90f46`.
797 backend tests passed (two opt-in live tests skipped), 24 browser tests passed, production
build and static checks passed. Five live production-pipeline runs: 298/300 overall,
40/40 report cases; provider fallback exercised six times. Raw-provider measurements are
retained alongside the final production-pipeline results.
