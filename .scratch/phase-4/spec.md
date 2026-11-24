# Phase 4: import bank and card statements (CSV and Excel)

Status: ready-for-agent
Integration branch: `phase-4/integration`
Tickets: `issues/` in this directory
Settled in a grilling session on 2026-11-01 (two rounds, every recommendation accepted).

## Problem Statement

Most of my money moves through my bank account and credit card, not through things I remember
to type into chat. To see my real spending in MoneyMoney I would have to re-type months of
transactions by hand. My bank already gives me all of it as a CSV or Excel download, but
MoneyMoney cannot read it. When I pay my credit card from my savings account, the payment
appears in both statements, and typing both in would count it as spending twice.

## Solution

On the Transactions page I choose **Import statement**, pick the account (say HDFC Savings) and
upload the bank's CSV or Excel file. MoneyMoney finds the table in the file, guesses which column
is the date, the description and the amounts, and shows me its guess once to confirm; it
remembers that **statement layout** for HDFC next time. I then see a **preview** of every row:
money out as expenses, money in as income, each with a category (my merchant rule, else an AI
guess, else Other). Rows I already imported are skipped, rows that look like something I typed by
hand are marked **likely duplicate** and unticked, and a credit card bill payment is suggested as
a **transfer** to my card account. I untick what I don't want, fix any category, and tap Import.
If I uploaded the wrong file, **Undo import** removes everything it created in one step.

## User Stories

**Uploading**

1. As a user, I want an "Import statement" button on the Transactions page, so that I can bring in a bank or card statement.
2. As a user, I want to pick which account the statement belongs to, so that every row is tagged with it.
3. As a user, I want to upload a CSV file, so that the common bank export works.
4. As a user, I want to upload an Excel (.xlsx) file, so that banks that only export Excel work.
5. As a user, I want files up to 5 MB and 5,000 rows to work while I wait, so that a year of statements imports in one go.
6. As a user, I want a clear message when a file is too big, empty, password-protected or not a statement, so that I know what to do.

**Reading the file**

7. As a user, I want MoneyMoney to skip the account-details lines at the top of the file and find the real table, so that exports with a preamble still work.
8. As a user, I want the first sheet that holds a table to be used, and to pick another sheet if that is wrong, so that multi-sheet Excel files work.
9. As a user, I want MoneyMoney to guess the date, description and amount columns (one amount column, or separate debit and credit columns), so that I don't map them by hand.
10. As a user, I want to confirm or correct that guess once, so that a wrong guess never imports wrong data.
11. As a user, I want the confirmed statement layout remembered for that account, so that the next import from the same bank needs no setup.
12. As a user, I want dates read day-first by default, shown in the preview and switchable, so that 03/04/2026 means 3 April unless I say otherwise.
13. As a user, I want amounts like "1,23,456.78", "₹ 500", "500.00 Dr" and "(500)" read correctly, so that Indian bank formats work.
14. As a user, I want the running balance column ignored, so that it is never mistaken for an amount.

**Preview**

15. As a user, I want a preview of every row before anything is saved, so that I stay in control.
16. As a user, I want money out shown as an expense and money in as income, so that the direction is clear.
17. As a user, I want each row's merchant picked out of the bank's description (for example Swiggy from a UPI line), so that rows are readable and merchant rules apply.
18. As a user, I want each row's category taken from my merchant rule, else an AI guess, else Other, so that most rows arrive filed.
19. As a user, I want the import to still work, with keyword guesses, when the AI is unavailable, so that an outage never blocks me.
20. As a user, I want to change any row's category in the preview, so that I can fix guesses before saving.
21. As a user, I want to untick rows I don't want, so that they are not imported.
22. As a user, I want rows from a file I already imported to be skipped automatically, so that importing the same file twice never doubles anything.
23. As a user, I want rows matching a transaction I already have in that account (same date, amount and direction) marked "likely duplicate" and unticked, so that hand-typed entries are not doubled.
24. As a user, I want to tick a likely duplicate back on, so that two genuinely identical payments can both be kept.
25. As a user, I want counts in the preview (to import, skipped, likely duplicates, transfers), so that I can check at a glance.

**Transfers between my own accounts**

26. As a user, I want a row whose description names one of my accounts, or reads like a card bill or self transfer, suggested as a transfer to that account, so that it is not counted as spending.
27. As a user, I want to accept, change the other account of, or reject a suggested transfer in the preview, so that wrong suggestions are easy to fix.
28. As a user, I want the matching row in my other account's statement (same amount, opposite direction, within 3 days) to join the existing transfer when I import that statement, so that one payment is never recorded twice.

**Saving and undo**

29. As a user, I want the confirmed rows saved together, so that an import is all or nothing.
30. As a user, I want imported transactions marked as imported and linked to their import, so that I can tell where they came from.
31. As a user, I want a row's category to teach my merchant rule only when I chose or changed it in the preview, so that hundreds of AI guesses don't become rules at once.
32. As a user, I want a list of my past imports (account, file name, date, rows imported), so that I can find one.
33. As a user, I want to undo an import, removing every transaction it created in one step, so that a wrong upload is easy to reverse.
34. As a user, I want an undone import's rows importable again later, so that I can redo it properly.
35. As a user, I want my summaries, search and chat answers to include imported transactions, so that my totals are complete.

**Safety**

36. As a user, I want another user's import or preview to be a 404, so that statements stay private.
37. As a user, I want the uploaded file itself not kept after the preview is built, so that my bank statement isn't stored longer than needed.
38. As a user, I want every import and undo recorded in the audit log, so that I can see what changed.

## Implementation Decisions

**Module**

- A new domain module **imports** owns statements, statement layouts, imports and their preview
  rows. It joins the import-linter "domain services" contract. File parsing (CSV, Excel, header
  and column detection, amount and date parsing) is pure functions with no database, so it is
  unit-tested on sample files.
- New dependencies: `openpyxl` (read-only mode) for .xlsx and `python-multipart` for uploads.
  .xls (old binary Excel) is out of scope.

**Flow and storage**

- Upload creates an **import** in status `previewing`, owned by the user and tied to one
  account, with its parsed rows stored as preview rows in the database. The file itself is not
  stored. A preview that is not confirmed expires after 24 hours and is deleted.
- The user confirms the layout (when new or changed), adjusts rows, then confirms the import.
  Confirming saves every ticked row as a transaction (`source = import`, `source_ref` = the
  import id, the account tagged, `idempotency_key` = the row fingerprint) in one database
  transaction with their audit events, and the import becomes `imported`.
- **Row fingerprint**: a hash of account, date, amount, direction, normalized description and
  the row's occurrence number among identical rows in that file, so the same file imported
  twice produces the same keys and is skipped, while two identical payments in one file stay
  distinct.
- **Undo** soft-deletes every transaction of that import (restorable like any delete),
  frees their fingerprints for a later re-import, and marks the import `undone`.
- An import's rows are in the account's currency.

**Statement layout**

- Stored per account: header row signature, which columns are date, description, amount (or
  debit and credit), optional reference, the date order (day-first or month-first), and the
  sheet name for Excel. When a new file's headers match the saved signature, the layout is
  applied without asking.

**Categories**

- Merchant from the narration by pure rules for common Indian formats (UPI, NEFT, IMPS, POS,
  card), with unit tests.
- Order: the user's merchant rule; else a batched AI guess (a new versioned prompt file,
  categories only, never amounts, in batches of about 50 rows); else Other. When the AI
  fails, the offline parser's keyword categories are used.
- Imported rows teach merchant rules only when the user picked or changed the category in the
  preview.

**Likely duplicates and transfers**

- A likely duplicate is an existing live transaction in the same account with the same date,
  amount and direction that is not itself from an earlier import of the same rows.
- A transfer is suggested when the narration names one of the user's accounts (by the account
  name rules from Phase 2) or matches card-bill and self-transfer patterns. When an existing
  transfer between the two accounts has the same amount within 3 days, the row is matched to it
  and not saved again; otherwise confirming creates the transfer.

**API and web**

- Endpoints: upload a statement (multipart, account id), get an import with its preview rows
  and detected layout, save the layout, update preview rows (tick, category, transfer target),
  confirm, undo, list imports. All scoped by user; another user's import is a 404. Contracts
  regenerated.
- Web: an "Import statement" flow on the Transactions page (account, file, layout confirmation
  when needed, preview table with counts and filters, confirm), the import marker on
  transaction rows, and an Imports list with undo.

**Limits**

- 5 MB and 5,000 data rows per file; larger files get a clear 413-style error. Processed in
  the request: no queue.

## Testing Decisions

- Behaviour at the highest seam: the HTTP API with real sample statements (integration tests
  that drop and re-migrate the test database), as the existing transaction and account API
  tests do.
- Sample files in the test fixtures, anonymized, shaped like HDFC, SBI, ICICI and Axis savings
  exports and one credit card export, including a preamble, separate debit and credit columns,
  "Dr/Cr" amounts, and a multi-sheet .xlsx.
- Pure unit tests for header detection, column guessing, date and amount parsing, merchant
  extraction, fingerprints and transfer suggestions.
- Re-importing the same file, undo then re-import, likely duplicates against hand-typed rows,
  and the two sides of a card payment are integration tests.
- The categorisation prompt is measured with a live eval over at least 5 runs (accuracy and
  latency), and the offline fallback is tested with the AI stubbed to fail.
- Prior art: `tests/integration/test_transactions_api.py`, the accounts tests, the transfer
  tests from Phase 2, and `tests/unit/test_understanding_eval.py`.

## Out of Scope

- Receipts (photos), PDF statements and old .xls files.
- Importing from chat.
- Statements in a currency other than the account's.
- Account balances, and checking the running balance column.
- Splitting an imported row with friends.
- Automatic bank connections (account aggregator), scheduled or emailed imports.

## Further Notes

- Glossary terms added: statement, import, statement layout, likely duplicate.
- Imports put an account on most transactions, which makes account balances (deferred in
  Phase 2) feasible in a later phase.
