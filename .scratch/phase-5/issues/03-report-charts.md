# 03: Accessible trend, category and merchant charts

**What to build:** Turn the report read model into responsive, keyboard-readable trend, category and
merchant visualizations, with tables containing the same values and exact transaction drill-down.

Spec: `../spec.md` → User stories 8-12, 15; Web contract.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] Expense/income trend, expense-by-category and top-merchant charts render only server-provided
  values and stay bounded by the response contract.
- [ ] Each chart has an accessible name, keyboard focus details and a table alternative containing
  every plotted value; colour is not the only series/category signal.
- [ ] Charts handle zero values, a single point, long labels and all supported currencies without
  NaN, Infinity or misleading geometry.
- [ ] Layout works at narrow mobile widths, in dark mode and with reduced motion.
- [ ] Selecting a category, merchant or time bucket opens Transactions with exact matching filters;
  add and test a merchant API filter if the existing text search cannot provide exact drill-down.
- [ ] No arbitrary chart configuration, HTML, CSS or formatter code crosses the API boundary.
- [ ] API checks (if the drill-down contract changes), web typecheck, lint and production build pass.

