# 02: Excel statements and messy files

**What to build:** A user uploads an .xlsx statement, or a CSV whose real table starts below a few
lines of account details, and MoneyMoney finds the header row on its own, uses the first sheet
that holds a table, and lets the user pick another sheet when that guess is wrong. The chosen
sheet is part of the statement layout.

Spec: `../spec.md` → User Stories 4, 6-8; Implementation Decisions → Module (openpyxl read-only), Statement layout.

**Blocked by:** 01

**Status:** done

- [x] .xlsx files are read with openpyxl in read-only mode, with dates and numbers from cells read correctly (real dates, not serial numbers or strings).
- [x] Header-row detection skips preamble lines in both CSV and Excel (unit tests on samples with 0, 5 and 15 preamble lines).
- [x] The first sheet with a table is used; the preview offers a sheet picker when there are several; the sheet name is saved in the statement layout.
- [x] Password-protected, corrupt or .xls files get a clear error.
- [x] Integration tests with an ICICI-shaped multi-sheet .xlsx and an Axis-shaped CSV with a preamble.
- [x] API checks, full pytest, and web typecheck, lint and build pass.

## Comments

Merged as `f211486`. The review added preview revision checks, positional header
signatures and tests for unfamiliar headings and empty workbooks. The full backend
suite passed 720 tests with one opt-in live test skipped. The production build passed
with webpack after Turbopack could not bind its local build-worker socket.
