# 02: Excel statements and messy files

**What to build:** A user uploads an .xlsx statement, or a CSV whose real table starts below a few
lines of account details, and MoneyMoney finds the header row on its own, uses the first sheet
that holds a table, and lets the user pick another sheet when that guess is wrong. The chosen
sheet is part of the statement layout.

Spec: `../spec.md` → User Stories 4, 6-8; Implementation Decisions → Module (openpyxl read-only), Statement layout.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] .xlsx files are read with openpyxl in read-only mode, with dates and numbers from cells read correctly (real dates, not serial numbers or strings).
- [ ] Header-row detection skips preamble lines in both CSV and Excel (unit tests on samples with 0, 5 and 15 preamble lines).
- [ ] The first sheet with a table is used; the preview offers a sheet picker when there are several; the sheet name is saved in the statement layout.
- [ ] Password-protected, corrupt or .xls files get a clear error.
- [ ] Integration tests with an ICICI-shaped multi-sheet .xlsx and an Axis-shaped CSV with a preamble.
- [ ] API checks, full pytest, and web typecheck, lint and build pass.

## Comments
