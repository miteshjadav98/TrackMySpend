# Build progress

Living build history. The latest checkpoint is at the end of the Phase 5 section.

## Done

- Repo layout: uv workspace (`backend/` = `finance-core` library, `apps/api` = `finance-api`).
- Local stack: `docker compose up -d` (Postgres 17 + Redis 7.4, test database auto-created).
- Database: SQLAlchemy 2.1 models in five schemas (`identity`, `ledger`, `chat`, `audit`, `agent`),
  Alembic migration `0001` (includes the 23 system categories), `alembic check` reports no drift.
- Core primitives: exact money (integer minor units, strict precision, Indian number formats),
  deterministic date and period resolution, UUIDv7 ids, clock abstraction, domain errors.
- Domain services (shared by REST, the agent and the future MCP server): auth (Argon2id, server-side
  sessions), profile, categories, transactions (idempotent inserts, optimistic locking, soft
  delete/restore, audit trail, keyset pagination), reports (SQL totals per currency, Redis cache keyed
  by a per-user data generation), conversations/messages.
- Redis helpers: fail-open client with circuit breaker, distributed lock, fixed-window rate limiter.
- LLM layer: provider-neutral interface, Gemini on Vertex AI (verified live: `gemini-3.5-flash-lite`,
  thinking `minimal`, ~1.3 s warm), offline rules engine (also the outage fallback), timeouts/failover.
- LangGraph workflow (`finance-v1`): understand → prepare_record ⇄ clarify (interrupt) → save → respond,
  plus summarize and search.
- Agent runtime: Postgres checkpointer (strict serde, `agent` schema), `FinanceAgent`, `ChatService`
  (replay, crash recovery, per-conversation lock, rate limits, answer validation), checkpoint retention,
  `python -m finance_core.manage migrate | prune-checkpoints`.
- FastAPI app (`python -m finance_api.serve`): auth, profile, categories, transactions, reports,
  conversations, chat turns over SSE (`/messages/stream`) and JSON (`/messages`). Smoke-tested over HTTP:
  clarify → resume, pending question survives reload, stale answers rejected, idempotent create
  (201 then 200), exact summaries, cross-site POST blocked.
- OpenAPI exported to `packages/contracts/openapi.json` (includes the `TurnEvent` stream schema).
- Tests: 139 passing (`uv run pytest`): unit tests plus integration tests against real Postgres/Redis
  covering auth, isolation, idempotency, optimistic locking, cache invalidation, Redis outage,
  clarify/resume, restart mid-question, double-texting, Gemini outage fallback, crash recovery, SSE.
- LLM quality: eval set in `tests/evals` (`RUN_LIVE_LLM=1`). Production pipeline =
  gemini-3.5-flash-lite (thinking `low`) + deterministic reconciliation with the rules engine:
  78/78 live runs correct, p50 1.26 s, p90 1.65 s (flash-lite `minimal` was only 51%).
- Static checks clean: ruff, mypy --strict, import-linter architecture contracts.

- Web app (`apps/web`, Next.js 16 + React 19 + Tailwind 4): sign in/up, chat with streamed turns and
  typed interaction cards (clarify, confirm, saved slip with undo/edit, summary, list, suggestions),
  running monthly tally, transactions page (filters, edit, delete/restore), settings. Types generated
  from OpenAPI into `packages/contracts`. Typecheck, lint and production build pass.

- Containers: `apps/api/Dockerfile` (uv, non-root, read-only code) and `apps/web/Dockerfile` (Next.js
  standalone). `docker compose --profile app up -d --build` runs migrate → API → web, all healthy;
  Gemini works in the container via mounted ADC (`GCLOUD_CONFIG_DIR`). Smoke-tested through the web
  proxy: register, streamed turn, ₹350.00 summary.
- Fixed: Next.js gzip on the `/api` rewrite buffered SSE until the turn finished; event streams now
  send `Cache-Control: no-store, no-transform` (first event 0.13 s instead of at the end).
- CI (`.github/workflows/ci.yml`, actions pinned to SHAs, Dependabot): ruff, mypy, import rules,
  pytest against Postgres/Redis services (fails instead of skipping when `CI` is set), `alembic
  check`, OpenAPI and TS contract drift, web typecheck/lint/build, both images build. Not yet run on
  GitHub: the repo has no remote.

- Database outages return 503 + `Retry-After` in the error envelope (was a generic 500); verified
  live by stopping Postgres (503 in 4 s, `/readyz` 503, recovers on restart without an API restart).
- Docs: `README.md` (setup, commands, env vars, migrations, contracts, tests),
  `docs/architecture.md` (design, workflow, failure behaviour, GCP deployment spec, scale plan),
  `docs/phase-1-report.md` (PRD report + PRD improvement suggestions). 142 tests passing.

**Phase 1 is complete.** The user tested the web app in the browser: no issues.

## Phase 2 (done, merged into `main` as 4904002)

Decided on 2026-10-27:

- Scope: merchant rules (learned from every save), accounts (no balances yet), transfers in
  chat and on the transactions page, account security (devices, sign out others, change
  password, forgot password with a console email sender).
- Not taken this phase: data export/deletion, measurable NFR targets, browser E2E tests.
- No GitHub remote yet; tickets live in a local markdown tracker.

Plan: `.scratch/phase-2/spec.md` and 11 tickets in `.scratch/phase-2/issues/`. Each ticket's
`Status:` line says whether it is merged. Built with the org-skills implement-spec flow:
implementers in worktrees (one test database each), merged one at a time into
`phase-2/integration`, then one code review over the whole branch.

Checkpoint 2026-10-28: tickets 01–05 merged (settings sections, merchant rules learn and
apply, accounts, security settings, merchant rules in Settings), plus a fix for `/chat`
hanging on a second visit (Next.js keeps pages alive in React `<Activity>`). 211 tests pass.

Checkpoint 2026-11-01: tickets 01–10 merged, and ticket 11 (docs) written. Added since the last
checkpoint: tagging transactions with an account (06), forgot password (07), transfers on the
API and the transactions page (08), transfers in chat with prompt `understand_v2` (09), "paid
from HDFC" in chat (10), and dark mode. `uv run pytest`: 332 passed, 1 skipped. Live eval:
100% over six runs of 23 cases (ticket 09), 93–100% per run over ten runs of 29 cases
(ticket 10), misses all model or provider noise, p50 about 1.1 s. Report:
[phase-2-report.md](phase-2-report.md).

Code review 2026-11-01 over the whole branch: approve with minor follow-ups, all fixed in
ticket 12. A category word in a merchant's name or said about another item no longer
overrides a merchant rule, plurals count as naming a category, "idk"/"skip" no longer
becomes an account or category, the account question offers "Cash", a new account in a
transfer takes the other end's currency and commits together with the transfer, and a blank
model reading is filled from the offline parser. `uv run pytest`: 357 passed, 1 skipped.

## Phase 3 (done, merged into `main` as bd8eaf6)

Split expenses with friends. Settled in a grilling session on 2026-11-01; spec
`.scratch/phase-3/spec.md`, ADR `docs/adr/0001-shares-are-each-users-own-expense.md`, and 8
tickets in `.scratch/phase-3/issues/` (each `Status:` line says whether it is merged).

Checkpoint 2026-11-01: tickets 01 to 07 merged (friends and invites, shared expenses, balances
and settlements, the friend's side, "Shared with you" notices, shared expenses in chat with
`understand_v3`, settlements and balances in chat with `understand_v4`), and ticket 08 (docs)
written. `uv run pytest`: 588 passed, 1 skipped. Live eval: 100% over five runs of 38 cases
(v3, p50 about 1.25 s) and 100% over five runs of 50 cases (v4, p50 about 1.37 s; about 0.13 s
slower than v3 on the same cases). Report: [phase-3-report.md](phase-3-report.md).

Code review 2026-11-01 over the whole branch, all findings fixed in ticket 09 (merge 39d6e7a):
accepting a friend invite now needs a one-time code sent to the invited email (sign-up never
proves the email); a friend who still owes money cannot be removed, and removed friends can be
brought back; a chat message mixing shared and ordinary expenses saves all or nothing; a
retried settlement request is saved once; a linked friend can tag their own account on a
settlement; and replies tell two friends with the same name apart by email. `uv run pytest`:
609 passed, 1 skipped.

## Phase 4 (merged to `main`)

Import CSV and Excel bank and card statements. Settled in a grilling session on 2026-11-01;
spec `.scratch/phase-4/spec.md`, 6 tickets in `.scratch/phase-4/issues/` (each `Status:` line
says whether it is merged), subagent briefing `.scratch/phase-4/build-notes.md`.

The integration branch includes CSV and Excel parsing, remembered layouts, full preview
pagination, one-to-one likely duplicate matching, merchant extraction and category labels,
and both sides of a transfer. Import confirmation and undo write audit events. Expired
previews are swept without waiting for an import request from the owner.

See the [Phase 4 report](phase-4-report.md) for the verification, Vertex evaluation and
limitations. The [README](../README.md#trying-a-statement-import-locally) has synthetic
statements for trying the flow locally.

## Phase 5 (built on `phase-5/integration`)

Charts and deterministic insights, with exact monetary totals kept separate by currency. The
spec is `.scratch/phase-5/spec.md`; six ordered tickets live in `.scratch/phase-5/issues/`.
Reporting stays in the modular monolith and uses Postgres plus the existing generation-keyed
Redis cache. FX conversion, report exports, budgets/forecasts and arbitrary generated UI remain
out of scope.

### Previous checkpoint — 24 November 2026 (saved before integration)

- Working checkout: `tms-phase4-integration/`; current branch: `phase-5/t02-reports`.
- Ticket 01 is complete on `phase-5/integration` (merge `94adb66`).
- The verified Next.js 16.4.6 security branch was merged into `phase-5/integration` as
  `f73e2d4`, before creating the ticket 02 branch. This integration merge has not been pushed.
- Ticket 02 is implemented and locally verified on `phase-5/t02-reports`, but **has not been
  merged or pushed**. Its tracker status remains unchanged until integration, per the issue
  tracker convention.
- Delivered for ticket 02: authenticated `/reports`, desktop/mobile navigation, URL-restored
  period and currency filters, date validation, exact spent/received/net and comparison cards,
  base currency first, loading/error/empty states, and report invalidation through the existing
  ledger mutation helper. Three/six-month selections include the current month to date plus
  the preceding two/five calendar months and pin explicit dates in the URL.
- Browser coverage found an expired-session loop: the proxy treated cookie presence as valid
  authentication and redirected login back to chat. Login now stays reachable with a stale
  cookie, and the app's sign-in redirect preserves the report query string. The regression
  failed before the fix and passed afterward.
- Verified: web typecheck, ESLint, Next.js production build, **12 Playwright tests passed**
  against the production build using installed Chrome, **5 reporting integration tests passed**
  against real Postgres/Redis, generated OpenAPI/TypeScript contracts had no drift, and the
  local database migration was already current. Desktop light/mobile dark screenshots were
  inspected. Full backend tests, full Python static checks and container builds were not rerun
  for this frontend ticket.
- Playwright tests use isolated API fixtures on port 3100 and never modify the demo ledger.
  CI now installs Chromium and runs the same browser suite after the web build.
- Local Postgres and Redis were started; dependencies are installed. No API or web demo server
  was left running, so port 3000 does not yet serve this new Reports page. No `.env` exists in
  this checkout; local HTTP API startup needs `COOKIE_SECURE=false`.
- User requested a checkpoint and stop before ticket integration, publishing or ticket 03.

### Resumed — 24 November 2026

Ticket 02's verified Reports page (`7a49b73`) is now integrated into `phase-5/integration`.
Its tracker acceptance criteria are complete. The Next.js 16.4.6 security update is included.
Ticket 02 was merged as `9fb6d7b` and both the ticket and integration branches were pushed.

### Ticket 03 testing checkpoint — 24 November 2026

- Current branch: `phase-5/t03-charts`, based on integration merge `9fb6d7b`.
- Implemented: income/expense SVG trend (circle/square and solid/dashed encodings), category and
  merchant bars, keyboard/hover values, exact table alternatives, mobile/dark/reduced-motion
  support and transaction drill-down. Money, category percentages and formatting come from the API.
- Transactions restore filters from the URL, including currency, exact merchant, remainder and
  uncategorized buckets. Shared Unicode merchant grouping keeps every report bucket identical to
  its paginated transaction rows. Browser coverage caught and fixed rapid typing losing characters
  while Next transitions URL state; the native input now preserves typing and restores history.
- Verification: web typecheck, lint and production build passed; **19 production-browser tests
  passed**; strict Python checks and import boundaries passed; **10 focused report/grouping tests
  passed**. Contracts regenerated and Alembic reports no drift. Desktop/light and mobile/dark chart
  screenshots inspected.
- Full backend suite: **776 passed, 2 skipped, 1 failed**. The failure is the existing
  `test_five_thousand_rows_import_in_one_go`: returning the confirmation detail hits the database's
  five-second statement timeout in the import-row matched-transaction join. It reproduces in
  isolation on both this branch and the unchanged pre-chart `tms-next-security` checkout. Do not
  describe the full suite as green. Investigate the import detail query's plan separately.
- User requested a running UI for testing. API is running on `127.0.0.1:8000`; production web is
  running on `127.0.0.1:3000`. Database and Redis readiness passed; `/login` returns 200 and the
  proxied unauthenticated `/api/v1/me` returns 401. The browser is open at the sign-in page with
  `/reports?period=this_year` preserved as its destination. Existing user data was not seeded or
  changed by the browser tests. Chat currently uses the default offline rules provider.
- This ticket is saved locally for user testing, **not merged or pushed**. Its tracker status
  remains unchanged until integration. Keep the current build stable while feedback arrives.

### Ticket 04 checkpoint — 24 November 2026

- User accepted ticket 03; merged locally as `fb90b08`, tracker recorded in `a74dbe8`.
- Ticket 04 implements typed server-side spending-change, largest-category and largest-named-
  merchant facts with period/currency/evidence. Ties are explicit; zero previous spending has
  no invented percentage; the aggregate Other merchants bucket is never called one merchant.
  Cards reuse the exact transaction drill-down links. Cache namespace is versioned for insights.
- Fixed the reproduced 5,000-row import timeout by counting unjoined import rows and materializing
  the bounded page before joining duplicate/category/account detail. The original failing test
  now passes without increasing the database timeout. All import regression cases pass.
- Verification: **779 backend tests passed, 2 opt-in live LLM tests skipped; 20 browser tests
  passed**. Ruff, strict mypy, import boundaries, web typecheck/lint and production build passed.
  OpenAPI and TypeScript contracts regenerated. No schema or prompt change.
- Local API and UI restarted on ports 8000 and 3000 with the new implementation. The API uses
  offline rules for chat. Ticket 04 is saved for user testing before integration/publication.
- Only ticket 02 and its integration were pushed earlier. Ticket 03 integration and ticket 04
  commits remain local; do not claim them published.

### Phase complete — 24 November 2026

Tickets 03 and 04 are integrated (`fb90b08`, `2850f60`); the accepted charts and deterministic
insights are included. Ticket 05 adds version-1 saved report snapshots in chat, trusted values
from `ReportService`, pinned full-report links, ordinary-summary compatibility and prompt v5.
Ticket 06 records the final behavior, currency policy, measured performance and verification.
All six ticket criteria are complete after their integration merges.

Final checks: **797 backend tests passed, 2 opt-in live tests skipped; 24 browser tests passed**.
Python/web static checks, production build, regenerated contracts and Alembic drift checks pass
(single head `0017`). Five live production-pipeline evaluations: **298/300** overall,
**40/40** report cases; six provider failures used rules fallback. Two remaining misses involve
existing shared-expense wording. The local 100,000-transaction benchmark's five-year report
p95 is **249.48 ms**, JSON **53,452 bytes**, with 61 trend and 11 merchant buckets per currency.
See [phase-5-report.md](phase-5-report.md) for exact commands, results and limits.

The owner requested ticket integration, a push of the completed phase and a refreshed local UI
for testing. The integration branch is the saved release candidate; main remains at Phase 4
until this local acceptance pass. Use the normal local API on port 8000 and web on port 3000.

## Next

1. Test Reports and chat requests such as “show my spending trend for six months” and
   “where did my money go this month?”. Full report links read the current ledger; saved chat
   cards keep their original snapshot.
2. After owner acceptance, merge the phase into main and verify hosted CI/container builds.
3. FX conversion, exports, budgets/forecasts, account balances and AG-UI/A2UI remain out of scope.

## Resume

```powershell
docker compose up -d
uv sync --all-packages
cd backend; uv run alembic upgrade head
```

## Phase 6 (planning started 25 November 2026)

The Phase 5 release candidate remains unchanged on `phase-5/integration` pending owner acceptance.
Phase 6 planning continues separately on `phase-6/integration`, based on the verified Phase 5
commit. The draft spec is `.scratch/phase-6/spec.md`; eight ordered tickets live in
`.scratch/phase-6/issues/`.

The proposed phase adds explicit dated balance anchors, asset/liability cash effects, credit-card
bills, simple loan due plans, English/Hinglish/Gujarati chat and review-before-send push-to-talk.
It keeps raw audio out of storage and routes accepted transcripts through the existing text
workflow. Implementation has not started; the draft assumptions and product boundaries still need
owner review.

### Ticket 01 implementation — 25 November 2026

The owner approved the Phase 6 draft. The local ticket branch is
`phase-6/t01-balances`. Migration `0018` adds loan accounts and optional signed, start-of-day
anchors. The accounts API returns signed balances, a per-currency overview of active accounts,
and paginated movements from each anchor. Each response uses one Postgres snapshot.

An account with a foreign-currency movement since its anchor appears under excluded accounts
with reason `currency_mismatch`. Its ledger shows that movement in the original currency.
Anchor corrections and clears take the previously observed `updatedAt` as `expectedUpdatedAt`.
Two clients editing the same anchor receive a conflict on the stale write.

The account-kind guard covers anchored accounts. Tickets 03 and 04 must extend it to
unanchored accounts that have a bill or debt plan when those records are introduced.

Verification on the ticket branch: 801 backend tests passed on an isolated Postgres database
and Redis DB 6. The two opt-in live Gemini evaluations skipped. Ruff, strict mypy, import
boundaries, web typecheck and lint passed. OpenAPI and TypeScript contracts regenerated.
Alembic reported a single head at `0018` and no schema drift.

### Ticket 02 implementation — 28 November 2026

Ticket 01 is integrated in `b8a7e6f`. The authenticated Accounts page is complete on
`phase-6/t02-accounts-page`. It groups known assets, liabilities and net position by currency
and names accounts excluded from each total. Account details show the saved opening balance
and paginated movements with links to ordinary transactions and shared expenses. Users can
review a signed opening balance before saving it, and stale edits prompt them to reopen the
editor. Settings remains the entry point for account management.

20 focused API tests passed, including before-and-after audit assertions for anchor changes.
All 30 browser tests passed in Chrome, along with web typecheck and lint. The webpack production
build passed. Turbopack could not bind its CSS worker port in the local environment.

The next ticket is [credit-card bills and payment allocation](../.scratch/phase-6/issues/03-credit-card-bills.md).
