# MoneyMoney

A chat-first personal finance assistant. You type "spent 350 on groceries yesterday" and
it records the expense, asks a short follow-up question when something is missing, and
answers "how much did I spend this month?" from exact database totals, never from the
model's memory.

- **Web:** Next.js 16 + React 19 + Tailwind 4 (`apps/web`)
- **API:** FastAPI with server-sent-event chat turns (`apps/api`)
- **Core:** domain services, Postgres, Redis, LangGraph workflow, Gemini on Vertex AI
  (`backend`, the `finance-core` library shared by the API and the future MCP server)

Status: Phase 1 of the PRD is complete. See [docs/phase-1-report.md](docs/phase-1-report.md)
for what was built and what comes next, and [docs/architecture.md](docs/architecture.md) for
how it fits together.

---

## Quick start

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/) 0.12+, Node.js 24. For Gemini
(optional, otherwise a built-in rules engine is used), also the gcloud CLI.

```bash
cp .env.example .env              # defaults work as-is with the offline rules engine
docker compose up -d              # Postgres 17 + Redis 7.4 (also creates moneymoney_test)
uv sync --all-packages            # Python 3.12 environment for API + core + dev tools
npm ci                            # web app + generated API types
npm run db:migrate                # Alembic migrations + LangGraph checkpoint tables
npm run dev:api                   # http://localhost:8000  (auto-reload)
npm run dev:web                   # http://localhost:3000  (in a second terminal)
```

Open <http://localhost:3000>, create an account, and start typing.

### Everything in containers

```bash
docker compose --profile app up -d --build
```

This builds both images, runs the migration as a one-shot job, then starts the API and the
web app on the same ports. Stop with `docker compose --profile app down` (add `-v` to wipe
the database).

### Using Gemini

```bash
gcloud auth application-default login
```

Then in `.env`, set `LLM_PROVIDER=gemini` and `GCP_PROJECT=<your project>` (Vertex AI API
enabled). For the containers, also set `GCLOUD_CONFIG_DIR` (see `.env.example`), which
mounts your credentials read-only. If Gemini is slow or down, the turn falls back to the
rules engine instead of failing, and the message metadata records `degraded: true`.

### Windows notes

- Set `PYTHONUTF8=1` (the test output and some logs contain ₹).
- The API uses a selector event loop on Windows, which psycopg's async driver requires.
  `npm run dev:api` handles this for you.

---

## Repository layout

| Path | What lives there |
| --- | --- |
| `backend/src/finance_core/` | Domain services (auth, users, categories, transactions, reports, conversations, audit), database, Redis helpers, LLM layer, LangGraph workflow, agent runtime |
| `backend/migrations/` | Alembic migrations (the only place schema changes happen) |
| `apps/api/src/finance_api/` | FastAPI app: routes, dependencies, security, error envelope, middleware |
| `apps/web/` | Next.js app: chat, transactions, settings |
| `packages/contracts/` | `openapi.json` exported from the API and the TypeScript types generated from it |
| `tests/` | `unit/`, `integration/` (real Postgres + Redis), `evals/` (LLM understanding cases) |
| `infrastructure/local/` | Docker Compose init scripts |
| `docs/` | Architecture, progress log, phase reports |

## Commands

| Command | Does |
| --- | --- |
| `npm run dev:api` / `npm run dev:web` | Run the API / web app with reload |
| `npm run db:migrate` | Apply migrations (also creates the checkpoint tables) |
| `npm run test:api` | All Python tests (integration tests need `docker compose up -d`) |
| `npm run check:api` | ruff lint + format check, mypy `--strict`, import-linter architecture rules |
| `npm run check:web` | TypeScript typecheck + ESLint |
| `npm run build:web` | Production build of the web app |
| `npm run contracts` | Re-export OpenAPI and regenerate the TypeScript types |
| `uv run python -m finance_core.manage prune-checkpoints` | Workflow checkpoint retention (run daily) |

CI (`.github/workflows/ci.yml`) runs all of the above, plus `alembic check`, contract-drift
checks, and both image builds.

## Configuration

Settings come from environment variables (or `.env` locally). The full list, with
defaults and comments, is in
[`backend/src/finance_core/config.py`](backend/src/finance_core/config.py). These are the
ones you are most likely to touch:

| Variable | Default | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `local` | `local`, `test`, `staging`, `production` |
| `DATABASE_URL` | local compose Postgres | `postgresql://…`; the driver prefix is added for you |
| `REDIS_URL` | local compose Redis | Cache, rate limits and locks only; the app keeps working without it |
| `ALLOWED_ORIGINS` | `http://localhost:3000` | Comma-separated. Used for CORS and the cookie-write origin check |
| `COOKIE_SECURE` | `true` | Set `false` only for plain-http local dev |
| `LLM_PROVIDER` | `rules` | `rules` (offline) or `gemini` |
| `GCP_PROJECT`, `VERTEX_LOCATION` | –, `global` | Vertex AI project and endpoint |
| `LLM_UNDERSTAND_MODEL`, `LLM_UNDERSTAND_THINKING` | `gemini-3.5-flash-lite`, `low` | Chosen from the eval set; see the config comments |
| `LLM_FALLBACK_TO_RULES` | `true` | Degrade to the rules engine instead of failing a turn |
| `LOG_JSON` | `true` | JSON logs for Cloud Logging; `false` gives readable local logs |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies trusted for `X-Forwarded-For` (used by rate limits) |
| `DATABASE_PREPARED_STATEMENTS` | `false` | Keep `false` behind a transaction-mode pooler |

Rate limits, timeouts, pool sizes and agent limits are also settings, so they can be tuned
per environment without code changes.

## Database migrations

- Apply: `npm run db:migrate`. In deployed environments this runs as a separate job
  before the new API version takes traffic. The API never runs DDL itself.
- Create: change the SQLAlchemy models, then
  `cd backend && uv run alembic revision --autogenerate -m "describe the change"`. Review
  the generated file, because autogenerate misses some things (check constraints, data
  migrations).
- Verify: `cd backend && uv run alembic check` must report no drift. CI enforces this.
- Workflow checkpoint tables (`agent` schema) are managed by LangGraph's own setup, which
  `migrate` also runs.

## API contracts

The API's OpenAPI document is the contract between backend and frontend. After changing a
request or response model:

```bash
npm run contracts   # writes packages/contracts/openapi.json and src/schema.d.ts
```

Commit both files. CI fails if either one is stale. The web app imports types from
`@moneymoney/contracts` and calls the API through `openapi-fetch`, so a breaking backend
change shows up as a TypeScript error.

## Tests

```bash
docker compose up -d
npm run test:api
```

- **Unit:** money, dates and periods, reconciliation, workflow logic, error mapping. These
  need no services.
- **Integration:** run against a separate `moneymoney_test` database and Redis db 1. They
  cover auth, user isolation, idempotency, optimistic locking, cache invalidation, a Redis
  outage, clarify/resume, a restart mid-question, double-texting, a Gemini outage, crash
  recovery and SSE. Locally they skip if the services are down; in CI they fail.
- **LLM eval (opt-in, calls Gemini):**
  `RUN_LIVE_LLM=1 uv run pytest tests/unit/test_understanding_eval.py -s`. Use repeated
  runs when comparing models, because a single run is noisy.

## Deployment

The target is Google Cloud: Cloud Run (web, API, migration job), Cloud SQL for
PostgreSQL, Memorystore for Redis, Vertex AI, and Secret Manager. Assumptions, required
settings and the scaling plan are in
[docs/architecture.md § Deployment](docs/architecture.md#deployment-on-google-cloud).
Infrastructure-as-code is not written yet (`infrastructure/gcp/` is empty).
