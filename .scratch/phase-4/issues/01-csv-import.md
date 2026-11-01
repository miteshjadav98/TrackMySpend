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

**Status:** done

- [x] A new `imports` domain module (joins the import-linter domain contract) with an Alembic revision on the single head for imports, preview rows and statement layouts; `uv run alembic check` reports no drift.
- [x] Pure parsing functions with unit tests on sample CSVs: column guessing (one amount column, or debit and credit columns), day-first and month-first dates, Indian amount formats ("1,23,456.78", "₹ 500", "500.00 Dr", "(500)"), the balance column ignored.
- [x] Row fingerprints as the spec defines (same file twice gives the same keys; two identical payments in one file stay distinct), with unit tests.
- [x] API: upload (multipart, account id), get an import with its preview rows and detected layout, save the layout, update preview rows (tick, category), confirm, undo, list imports. Scoped by user; another user's import is a 404.
- [x] The file is never stored; an unconfirmed preview expires after 24 hours.
- [x] Confirm saves every ticked row as a transaction (`source = import`, account tagged, fingerprint as idempotency key) in one database transaction with audit events; re-importing the same file skips those rows and the preview counts them as skipped.
- [x] Imported rows teach a merchant rule only when the user picked or changed the category in the preview.
- [x] Undo soft-deletes every transaction of the import, frees their fingerprints, and marks the import undone; a re-import afterwards brings them back.
- [x] Limits: 5 MB and 5,000 data rows, with clear errors for too big, empty, or not a statement.
- [x] Web: "Import statement" on the Transactions page (account, file, layout confirmation when needed, preview table with counts, confirm), an import marker on transaction rows, and an Imports list with undo. Works in dark mode and with React `<Activity>`.
- [x] Integration tests with sample HDFC- and SBI-shaped CSVs: import, re-import skipped, undo then re-import, layout remembered, another user's import 404.
- [x] `npm run contracts` committed; API checks, full pytest, and web typecheck, lint and build pass.

## Comments

Implementer (branch `phase-4/t01-csv-import`): built end to end; all boxes ticked.

- Seams for later tickets. `imports/readers.py` returns rows of cells (`list[list[Cell]]`),
  where a cell may be text, a number or a date; `imports/table.py::locate_table` finds the
  header row and enforces the limits for any reader, so Excel (02) adds a reader and, if it
  needs, a better `find_header_row` in `columns.py`. `imports/categorise.py::CategoryPicker`
  is the one place a row's category is chosen (rule, else Other; `prepare` is where batched AI
  goes, `category_source` already allows `ai` and `keyword`). `ImportService._rebuild_rows`
  builds preview rows; likely duplicates (03) and transfers (05) add their statuses next to
  the "already imported" check in `_preview_row`. Preview rows already carry `status`
  (`to_import`, `skipped`, `likely_duplicate`, `transfer`) and `note`.
- `imports/merchant.py::extract_merchant` is a small first version (skips channel words, bank
  codes and reference numbers); ticket 04 replaces its body.
- `TransactionService.create_imported` is a bulk insert (one INSERT per 500 rows) because
  `create_resolved` caps a batch at 20 and took ~30 s for 5,000 rows; 5,000 rows now confirm in
  about 5 s. `MerchantRuleService.categories_for_many` looks up rules for all rows in one query.
- Undo clears each transaction's idempotency key (also ones the user deleted by hand), which is
  what frees the fingerprints. A transaction the user deleted by hand before any undo still
  holds its key, so re-importing the file skips that row as "Already imported".
- Previews keep each row's raw cells so a changed layout can re-read them without the file;
  they are cleared on confirm. Changing the layout rebuilds the rows, so ticks and category
  picks made before it are lost.
- Preview edits (`PATCH .../rows`) write one `import.rows_changed` audit event per call.
- Not done: the Excel/.xlsx path (ticket 02). The browser flow was typechecked, linted and
  built, but not clicked through by hand.

Merged into phase-4/integration. Merge checks: pytest 703 passed, 1 skipped (live LLM eval); check:api, check:web, web build, contracts and alembic check all clean.
