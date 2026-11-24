# Phase 4 report

Phase 4 adds bank and card statement imports to the Transactions page. An import brings
one account's CSV or Excel statement into a preview for review and confirmation. The
[Phase 4 spec](../.scratch/phase-4/spec.md) defines the scope and
the [README](../README.md#trying-a-statement-import-locally) includes sample files and a
walk-through.

## Scope delivered

| Ticket | Behaviour |
| --- | --- |
| 01 | CSV upload, layout confirmation, row selection, exact reimport detection, import history and undo |
| 02 | Read-only Excel parsing, preamble detection, worksheet selection and a preview revision check |
| 03 | One-to-one likely duplicate matching, with the existing transaction shown and a selection override |
| 04 | Merchant extraction, batched Gemini category labels and keyword fallback |
| 05 | Transfer suggestions, another-account selection, and one ledger transfer across both statement sides |
| 06 | README walk-through, architecture, glossary, progress and this report |

## Verification

| Check | Result |
| --- | --- |
| Unit and integration suite against isolated Postgres and Redis | 768 passed, 2 opt-in live tests skipped |
| Ruff lint and formatting, strict mypy and import boundaries | Passed |
| OpenAPI and TypeScript contracts | Regenerated with no drift |
| Database migration | One Alembic head (`0017`), no schema drift |
| Web typecheck, ESLint and production build | Passed. The build used webpack because Turbopack's worker could not bind a port in the sandbox. |

The integration tests cover concurrent layout confirmation, stale worksheet and duplicate
previews, row editing past position 500, reimports, undo, provider failure, expired preview
cleanup and both orders of importing a card payment. The production build reported an
advisory for the installed Next.js version.

## Live categorisation evaluation

Gemini on Vertex (`gemini-3.5-flash-lite`, thinking `low`) ran
`statement_categories_v1` on 40 labelled synthetic bank and card narrations per batch.
The cases span expense and income categories and include ambiguous rows with a null label.

| Run | Correct | Batch latency |
| --- | --- | --- |
| 1 | 40 / 40 | 2,870 ms |
| 2 | 40 / 40 | 2,582 ms |
| 3 | 40 / 40 | 2,357 ms |
| 4 | 40 / 40 | 2,560 ms |
| 5 | 40 / 40 | 2,457 ms |

Across these five batches, latency was **2,560 ms p50** and **2,813 ms p95**. The ordinary
test suite covers provider failure, merchant-rule precedence and unknown categories.

## Statement import limits

- One account and currency per statement. CSV and `.xlsx` uploads can contain up to
  5,000 data rows and occupy up to 5 MB. Excel also has safeguards for expanded size and
  sparse worksheets. PDF, receipts, `.xls` and bank connections remain out of scope.
- A new header signature or worksheet requires checking the layout. Unfamiliar headers may
  need manual column selection. Switching worksheets rebuilds the preview, and an unsaved
  preview expires after 24 hours.
- A workbook must be unlocked and resubmitted to choose a different worksheet. The server
  keeps a temporary digest and parsed preview rows, then clears the digest and raw cells on
  confirmation.
- Merchant and transfer suggestions depend on the narration and existing accounts. Check
  ambiguous rows before confirming, especially if two payments share an amount and date.
- Gemini has a 12-second budget per preview rebuild. Batches still pending at the deadline
  use keyword suggestions, so a large statement can show a mixture of category sources.
- The API removes expired previews at startup and every 15 minutes while running. A
  scale-to-zero deployment can schedule `prune-import-previews` to sweep while the API
  is idle.

## Release status

Phase 4 is integrated locally on `phase-4/integration`. Merging into `main` awaits owner
approval. Phase 5 covers charts, insights and totals across currencies.
