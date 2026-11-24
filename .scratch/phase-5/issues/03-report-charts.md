# 03: Accessible trend, category and merchant charts

**What to build:** Turn the report read model into responsive, keyboard-readable trend, category and
merchant visualizations, with tables containing the same values and exact transaction drill-down.

Spec: `../spec.md` → User stories 8-12, 15; Web contract.

**Blocked by:** 01, 02

**Status:** done

- [x] Expense/income trend, expense-by-category and top-merchant charts render only server-provided
  values and stay bounded by the response contract.
- [x] Each chart has an accessible name, keyboard focus details and a table alternative containing
  every plotted value; colour is not the only series/category signal.
- [x] Charts handle zero values, a single point, long labels and all supported currencies without
  NaN, Infinity or misleading geometry.
- [x] Layout works at narrow mobile widths, in dark mode and with reduced motion.
- [x] Selecting a category, merchant or time bucket opens Transactions with exact matching filters;
  add and test a merchant API filter if the existing text search cannot provide exact drill-down.
- [x] No arbitrary chart configuration, HTML, CSS or formatter code crosses the API boundary.
- [x] API checks (if the drill-down contract changes), web typecheck, lint and production build pass.


## Comments

User tested and accepted the UI on 24 November 2026. Integrated from `d2ec015`;
19 browser tests, strict API/web checks and production build passed. Full backend suite
found an existing bulk-import timeout, reproduced on the pre-chart checkout; tracked next.
