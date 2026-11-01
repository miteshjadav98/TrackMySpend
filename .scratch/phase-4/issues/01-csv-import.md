# 01: Import a CSV statement end to end

**What to build:** On the Transactions page a user chooses "Import statement", picks an account,
uploads a CSV, confirms MoneyMoney's guess of the date, description and amount columns (once per
account; the statement layout is remembered), sees a preview of every row (money out as expense,
money in as income, category from their merchant rule else Other), unticks or recategorises
rows, and imports them. Importing the same file again skips every row already imported. Undo
removes everything one import created. Excel, likely duplicates, AI categories and transfers are
later tickets.

Spec: `../spec.md` → User Stories 1-3, 5-6, 9-16, 18 (rule or Other only), 20-22, 25, 29-38;
Implementation Decisions → Module, Flow and storage, Statement layout, Limits.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A new `imports` domain module (joins the import-linter domain contract) with an Alembic revision on the single head for imports, preview rows and statement layouts; `uv run alembic check` reports no drift.
- [ ] Pure parsing functions with unit tests on sample CSVs: column guessing (one amount column, or debit and credit columns), day-first and month-first dates, Indian amount formats ("1,23,456.78", "₹ 500", "500.00 Dr", "(500)"), the balance column ignored.
- [ ] Row fingerprints as the spec defines (same file twice gives the same keys; two identical payments in one file stay distinct), with unit tests.
- [ ] API: upload (multipart, account id), get an import with its preview rows and detected layout, save the layout, update preview rows (tick, category), confirm, undo, list imports. Scoped by user; another user's import is a 404.
- [ ] The file is never stored; an unconfirmed preview expires after 24 hours.
- [ ] Confirm saves every ticked row as a transaction (`source = import`, account tagged, fingerprint as idempotency key) in one database transaction with audit events; re-importing the same file skips those rows and the preview counts them as skipped.
- [ ] Imported rows teach a merchant rule only when the user picked or changed the category in the preview.
- [ ] Undo soft-deletes every transaction of the import, frees their fingerprints, and marks the import undone; a re-import afterwards brings them back.
- [ ] Limits: 5 MB and 5,000 data rows, with clear errors for too big, empty, or not a statement.
- [ ] Web: "Import statement" on the Transactions page (account, file, layout confirmation when needed, preview table with counts, confirm), an import marker on transaction rows, and an Imports list with undo. Works in dark mode and with React `<Activity>`.
- [ ] Integration tests with sample HDFC- and SBI-shaped CSVs: import, re-import skipped, undo then re-import, layout remembered, another user's import 404.
- [ ] `npm run contracts` committed; API checks, full pytest, and web typecheck, lint and build pass.

## Comments
