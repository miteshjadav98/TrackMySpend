# Phase 5: reports, charts and deterministic insights

Verified on 24 November 2026. Tickets 01–06 are delivered on `phase-5/integration`;
main remains at the Phase 4 release while the owner tests the completed phase.

## Delivered behavior

The authenticated Reports page provides URL-restored period/currency filters, exact spent,
received and net KPIs, equal-length preceding-period comparisons, income/expense trends,
exhaustive category shares, top-ten merchants plus a remainder, and three deterministic insight
kinds. Daily, weekly and monthly buckets include zero gaps and stay below the 120-bucket cap.
The current month is partial; 3/6-month presets include it plus the preceding 2/5 calendar months.

Currency sections remain independent, with the base currency first. There are no exchange rates
or combined monetary totals. Transfers and deleted transactions are excluded; an owner's share
of a shared expense is included. Existing generation invalidation refreshes reports after ledger
mutations. SQL and the domain service own every amount, percentage, grouping and display string.

Charts use owned SVG/CSS, accessible exact tables, keyboard focus details, distinct line/shape
encodings, and links to exact transaction filters. Merchant normalization and remainder selection
are shared with transaction search, including Unicode names and unnamed merchants.

Explicit chat trend/breakdown/insight questions use the same service. A fixed version-1 report
interaction stores one currency, exact metrics, bounded dimensions, generation time and pinned
Reports links. Retries/reloads preserve the original snapshot; new questions and full reports
read current data. Ordinary total questions keep their existing summary card. Invalid report
ranges are rejected explicitly. The language model supplies no financial values or UI layout.

The pre-existing 5,000-row import regression exposed during this phase was also fixed: a
materialized bounded import-detail page prevents duplicate-match joins from expanding over
all rows. The test passes without raising the five-second statement timeout.

## Verification

| Check | Result |
| --- | --- |
| `npm run check:api` | Ruff and formatting pass; strict mypy passes for 147 sources; both import contracts kept |
| `uv run pytest` | 797 passed, 2 skipped in 49.33 s |
| `npm run check:web` | Next route generation, TypeScript and ESLint pass |
| `npm run build:web` | Next.js 16.4.6 production build passes |
| `PLAYWRIGHT_CHANNEL=chrome npm run test:browser -w web` | 24 passed against the production app in 7.3 s |
| `npm run contracts` | OpenAPI and TypeScript regenerated; repeated generation is stable |
| `uv run alembic -c backend/alembic.ini heads` | Single head: `0017` |
| `uv run alembic -c backend/alembic.ini check` | No new upgrade operations detected |
| `git diff --check` | Pass |

The two default-suite skips are opt-in live understanding and statement-category evaluations;
understanding was measured separately below. This phase did not change statement classification.
Integration tests run against real isolated Postgres/Redis and cover report boundaries, gap
filling, comparison math, category/merchant reconciliation, cache invalidation, Redis failure,
transfers, deleted rows, shared expenses and user isolation. Chat tests additionally cover replay,
restart, old pending questions, fake model amounts, one/multiple currencies and ordinary totals.

Browser coverage includes date/currency reload/history, invalid custom dates, loading/retry,
empty states, stale-cookie login, ledger invalidation, exact drill-down, zero-value geometry,
JPY/KWD server formatting, keyboard chart focus, exact tables, narrow dark layouts and reduced
motion. Saved chat reports load beside old summary interactions and survive reload. This is
functional browser/accessibility coverage, not a formal screen-reader or WCAG certification.
Container builds and hosted CI were not rerun for this phase.

## Read performance at 100,000 transactions

Reproducible command:

```bash
uv run python -m tests.evals.benchmark_reports --output .scratch/phase-5/report-benchmark.json
```

The runner refuses databases other than `moneymoney_test`. It inserts one synthetic user and
100,000 transactions in one uncommitted transaction, then rolls everything back. Distribution:
1,830 dates, two currencies, 1,000 merchants, 80% expenses, remaining rows income, and some
unnamed merchants. Each row below contains 20 samples on local Docker Postgres 17. Timings include
service computation and JSON serialization. Redis is bypassed; Postgres/OS buffers are retained,
so these are cold application-cache reads, not cold-disk or end-to-end network measurements.

| Request | p50 ms | p95 ms | Maximum ms | JSON bytes | Maximum buckets per currency |
| --- | ---: | ---: | ---: | ---: | --- |
| Current month, 24 days | 10.28 | 14.02 | 28.86 | 24,531 | 24 trend / 11 merchant |
| Year to date, 328 days | 70.86 | 86.69 | 88.95 | 42,295 | 47 trend / 11 merchant |
| Five years, 1,830 days | 231.13 | 249.48 | 251.33 | 53,452 | 61 trend / 11 merchant |
| Named merchant drill-down, five years | 57.12 | 58.87 | 60.00 | 21,898 | 50 transaction rows |
| Other merchants drill-down, five years | 129.42 | 130.76 | 131.19 | 21,965 | 50 transaction rows |

All measured p95 values meet the one-second local target. The benchmark does not establish a
production availability SLO, concurrent-user capacity, maximum-category payload or worst-case
merchant cardinality. Repeat on deployment hardware and real distributions before scaling.
Raw measurements are in [report-benchmark.json](../.scratch/phase-5/report-benchmark.json).

## Repeated live intent evaluation

Prompt `understand_v5`, Vertex model `gemini-3.5-flash-lite`, thinking `low`, five runs of
60 fixed cases at concurrency four. The eight new explicit report cases are included alongside
ordinary totals, record/search, accounts, transfers, shared expenses and settlements.

```bash
uv run python -m tests.evals.run_understanding --runs 5 --concurrency 4 \
  --env-file ../TrackMySpend/.env --output .scratch/phase-5/understand-v5-production.json
```

The env-file path above is the local checkout's existing configuration; use your own configured
file elsewhere. No credentials or real user messages are saved in the evaluation artifacts.
The runner now exercises the actual provider → rules fallback → reconciliation path and records
raw correctness and degraded requests separately. Fallback requests are never counted as raw
provider successes. Report acceptance requires every report case correct in every run; overall
acceptance requires at least 90% per run.

| Run | Final correct | Report cases correct | Raw provider correct | Fallback requests | Provider p50 ms | Provider p95 ms |
| --- | --- | --- | --- | ---: | ---: | ---: |
| 1 | 60/60 | 8/8 | 46/60 | 0 | 1,299.5 | 2,246.4 |
| 2 | 58/60 | 8/8 | 37/60 | 1 | 1,249 | 4,598.3 |
| 3 | 60/60 | 8/8 | 46/60 | 0 | 1,356.5 | 2,233.1 |
| 4 | 60/60 | 8/8 | 43/60 | 3 | 1,327 | 2,155.6 |
| 5 | 60/60 | 8/8 | 45/60 | 2 | 1,254.5 | 2,228.7 |

Final correctness is 298/300 (99.3%); explicit reports are 40/40. Six requests used rules fallback.
Latency percentiles above exclude fallback requests and measure the provider call, not the whole
turn. Two misses were existing shared-expense phrases split into extra model drafts; the new
report requests were all correct. Raw output needs reconciliation; its accuracy is not claimed
to be release quality on its own.

Two earlier provider-only batches also met the overall 90% threshold but failed the stricter
all-report gate because of provider exceptions (not incorrect report parsing). Those unsuccessful
measurements are retained in [understand-v5-evaluation.json](../.scratch/phase-5/understand-v5-evaluation.json)
and [understand-v5-confirmation.json](../.scratch/phase-5/understand-v5-confirmation.json). The final
production-pipeline results are [understand-v5-production.json](../.scratch/phase-5/understand-v5-production.json).
The prompt did not change between these measurements.

## Limits and next steps

- Reports accept at most 1,830 inclusive days. Offline chat handles the documented 3/6-month,
  named-month, year, day and ISO-range forms; unfamiliar language may require explicit dates.
- Chat snapshots intentionally retain old totals. Full-report links preserve filters and read
  current data; opening them after ledger edits can produce new values.
- Reports use existing read-committed database sessions. Concurrent edits between aggregation
  queries can require refresh; this is not an immutable accounting-statement facility.
- Merchant output is bounded; categories are exhaustive. Extremely many distinct merchants or
  categories still increase aggregation work. Re-measure before adding infrastructure.
- Insight kinds are limited to spending change, largest category and largest named merchant.
  No FX conversion, exports, budgets, forecasts, anomalies, advice, account balances, net worth,
  scheduled delivery, AG-UI or A2UI ships here.
- The next user-facing roadmap phase is voice/Indian languages and debt/credit-card bill tracking.
  Before hosted release, run CI/container builds and repeat performance measurements in that
  environment. The owner is testing the completed phase locally before merging it into main.
