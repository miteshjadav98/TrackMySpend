# Phase 1 report

**Deliverable: a working chat-based personal expense tracker. Done.** It runs locally
natively or fully in Docker. All ten MVP acceptance criteria in PRD §19 are met, and so is
most of Phase 2.

Date: 2026-10-26 · Branch: `phase-1/foundation`

## Completed functionality

### PRD Phase 1 scope

| PRD item | Status | Where |
| --- | --- | --- |
| Repository and local setup | Done | uv + npm workspaces, `docker compose`, [README](../README.md) |
| Authentication and user isolation | Done | Server-side sessions, Argon2id, origin check, per-user scoping everywhere |
| PostgreSQL schema and migrations | Done | 5 schemas, Alembic `0001`, `alembic check` in CI |
| FastAPI endpoints | Done | Auth, profile, categories, transactions, reports, conversations, chat (SSE + JSON) |
| Next.js chat UI | Done | Streamed chat with interaction cards, transactions page, settings |
| Gemini integration | Done | Vertex AI `gemini-3.5-flash-lite`, structured output, rules fallback |
| Basic LangGraph workflow | Done | `finance-v1`: understand → clarify ⇄ prepare → save → respond, plus summarize and search |
| Manual expense and income entry | Done | Natural-language chat, several transactions per message |
| Transaction history | Done | Filters, keyset pagination, edit, delete and restore |
| Accurate monthly summaries | Done | SQL totals per currency, in the user's timezone; tested equal to the reports API |

### Pulled forward from Phase 2

These were needed to make Phase 1 correct, so they are already done:

- Typed, dynamic UI response schemas.
- Clarification and confirmation flows.
- Durable Postgres checkpoints.
- Editing with optimistic locking.
- Three-layer duplicate prevention.
- Redis caching with generation-based invalidation.
- Authorization and financial-calculation tests.

Left from Phase 2: long-term preferences beyond the profile, such as merchant → category
memory.

### MVP acceptance criteria (PRD §19)

| # | Criterion | Evidence |
| --- | --- | --- |
| 1 | Users access only their own records | `tests/integration/test_isolation.py`: cross-user reads and writes get 404 |
| 2 | Expenses and income through chat | `test_one_message_records_a_complete_expense`, `test_several_transactions_in_one_message` |
| 3 | Targeted follow-up questions | `test_missing_category_is_asked_then_answered_by_option`, `test_inferred_amounts_must_be_confirmed` |
| 4 | Adaptive UI with persisted workflow state | `test_pending_question_survives_a_restart`, interaction cards in the web app |
| 5 | Search and correct transactions | Chat search, transactions page, PATCH with version check |
| 6 | Summaries match the database | `test_chat_summary_equals_the_reports_api`, `tests/integration/test_reports.py` |
| 7 | No accidental duplicates | `test_retried_messages_never_duplicate`, idempotent `POST /transactions` |
| 8 | Cache stays consistent after updates | `test_summary_matches_the_ledger_and_tracks_every_write` (cached reads after create, edit and delete) |
| 9 | Failures handled gracefully | Gemini outage, Redis outage, crash recovery, and database → 503 tests |
| 10 | Automated tests, reproducible setup | 142 tests, CI workflow, README quick start |

## Tests executed

| Check | Result |
| --- | --- |
| `uv run pytest` (unit + integration, real Postgres 17 + Redis 7.4) | **142 passed**, 1 skipped (the live LLM eval, opt-in) |
| Live LLM eval (`RUN_LIVE_LLM=1`, 13 cases × 6 runs, Gemini) | **78/78 correct**, p50 1.26 s, p90 1.65 s |
| ruff lint + format, mypy `--strict`, import-linter (2 architecture contracts) | Clean |
| `alembic check` (models vs. migrations) | No drift |
| Web: `next typegen` + `tsc`, ESLint, `next build` | Clean |
| Docker: both images build; `compose --profile app` runs migrate → API → web | All healthy |
| End-to-end through the web proxy (containers, real Gemini) | Register 201 → streamed turn (first event 0.13 s) → saved → summary ₹350.00 |

Found and fixed while testing the containers: in the production Next.js server, the gzip
on the `/api` rewrite buffered the chat stream until the turn ended. Streams now send
`Cache-Control: no-store, no-transform`, and a test asserts it.

## Known limitations

### Not verified yet

- No one has used the web app in a browser beyond my own checks. Your testing is the next
  input.
- CI has never run on GitHub, because the repo has no remote. Every step does pass
  locally.
- There are no browser end-to-end tests (Playwright). The web app is covered by types,
  lint and build only.
- The browser-disconnect and turn-timeout paths are implemented but not tested.

### Product gaps

- Chat records expenses and income only. Transfers exist in the data model and API, but
  the chat can't record them.
- There is no "add transaction" form. You add by chat and edit on the transactions page.
- There is no password reset, email verification, account deletion or data export.
- Multi-currency totals are shown per currency with no conversion.
- Falling back to the rules engine during a Gemini outage is invisible to the user (it is
  only logged).

### Deployment

- Not deployed. `infrastructure/gcp/` is empty; the target layout is specified in
  [architecture.md](architecture.md#deployment-on-google-cloud).
- Behind a Cloud SQL pooler, two connection options (`search_path`, `statement_timeout`)
  must move to the database role. This is documented, not automated.

### Quality

- The LLM eval set is small: 13 English cases. There are no Hinglish or Gujarati cases
  yet, and no Indian number words ("dedh sau", "2 lakh").

## Next recommended step

1. **You test the app** at <http://localhost:3000>. It's running now via
   `docker compose --profile app up -d`. I'll fix what you find.
2. **Push to GitHub** so CI runs on every change. This needs a remote: create an empty repo
   and give me the URL.
3. **Finish Phase 2:**
   - long-term preferences (merchant → category memory, which you can inspect, edit and
     delete)
   - transfers in chat
   - the account and data-rights items below, if you accept them
4. **Then Phase 3** (CSV/Excel, then receipts and PDF statements), or a GCP staging
   deployment first if you want it online early.

## Suggested PRD improvements

Ordered by how much they would change later work.

1. **Add accounts (bank, card, wallet, cash) as a first-class entity before Phase 3.**
   - Statement imports need an account to land in.
   - Transfers need from/to accounts; otherwise they are just a label.
   - Balances, credit-card bills and debt tracking (Phase 6) all depend on accounts.

   Adding a nullable `account_id` now is cheap. Retrofitting it after imports exist is a
   painful data migration.
2. **Add a "privacy and data rights" section.** Cover export of all data, account deletion,
   transcript retention and consent. Users are in India (INR, Gujarati), so this falls
   under the DPDP Act 2023. Today chat transcripts, which contain financial details, are
   kept forever. The PRD already says not to log full conversations, so it should also set
   a retention period for stored ones.
3. **Make the non-functional targets measurable.** Suggested targets:
   - p95 chat turn under 3 s
   - 99.9% monthly availability
   - eval accuracy of at least 95% on at least 100 cases before each release
   - a per-user daily LLM cost cap

   I picked values like these implicitly; the PRD should own them. It should also make the
   LLM eval set a release gate per phase, extended with each new language and input type.
4. **Decide the multi-currency policy before Phase 4 charts.** Either show per-currency
   totals (the current behaviour) or convert to the base currency using the rate on the
   transaction date. Conversion needs a rate source and stored rates, so a summary can
   always be reproduced.
5. **Specify the "memory" UX in Phase 2.** The PRD requires that users can inspect, correct
   and delete preferences. Define it concretely: a settings page listing learned
   merchant → category rules, each with an "undo learning" action. Learning should only
   happen from confirmed saves.
6. **Add account security to Phase 2.** Password reset, which needs an email provider in
   the stack. A session list with "sign out other devices". Optional TOTP. A finance app
   with login only will not pass a security review.
7. **Make Indian-language number handling explicit in Phase 6 voice:**
   - Gujarati digits (૧૨૩)
   - lakh and crore
   - words like "dedh sau" (150) and "adhi" (half)
   - code-mixed input

   Add these cases to the eval set when voice starts, not after.
8. **Phase 5 MCP authentication:** name OAuth 2.1 (what the MCP spec uses for remote
   servers), with a per-tool confirmation policy for writes. Define the Super Bot handoff
   contract (what context it passes, and who confirms).
9. **Product metrics:** add them to the observability section, to measure parsing
   quality in production:
   - share of turns that needed a clarification
   - share of saves edited or undone within 10 minutes
   - degraded-turn rate
