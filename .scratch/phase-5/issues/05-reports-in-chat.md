# 05: Charts and insights in chat

**What to build:** Explicit trend, breakdown and insight questions return one fixed report
interaction based on `ReportService`, with a deep link to the full Reports page. Existing compact
summary questions do not change.

Spec: `../spec.md` → User stories 17-19; Chat contract.

**Blocked by:** 01, 03, 04

**Status:** ready-for-agent

- [ ] A versioned `report` interaction carries a bounded trusted report payload and reproducible
  Reports-page URL; old stored interactions continue to load.
- [ ] Understanding distinguishes explicit trend/breakdown/insight requests from ordinary totals;
  the offline parser covers the same supported phrases.
- [ ] Workflow nodes call `ReportService`; no model output supplies amounts, grouping, percentages,
  data points or currency conversion.
- [ ] Chat renders an accessible compact report card and links to the full report with matching
  period/currency filters.
- [ ] Unit/integration tests cover routing, replay, restart, one and multiple currencies, ordinary
  summary regression and equality with the reports API.
- [ ] New prompt cases are added to the eval set and measured over repeated live runs before release.
- [ ] Contracts, API checks, full pytest and web checks pass.

