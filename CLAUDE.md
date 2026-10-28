# MoneyMoney

Chat-first personal finance tracker. `backend/` is `finance_core`, the library that holds every
domain service and the LangGraph agent; `apps/api` is the FastAPI service over it; `apps/web` is
the Next.js app.

- **Architecture**: read `docs/architecture.md` before changing a module's shape, the data
  model, or the chat workflow.
- **Commands and setup**: `README.md` and the root `package.json` scripts.
- **Domain terms**: `GLOSSARY.md`. Name things the way it does.

## Readable code

The owner walks other people through this code, so write it to be explained:

- Plain, specific names; one job per function.
- A short docstring on each module and public class saying what it is for.
- Comments give the reason behind a choice, in one or two lines.
- Tests are named as sentences about behaviour (`test_retried_messages_never_duplicate`).

## Rules the code depends on

- Money is integer minor units plus an ISO currency. Totals come from SQL. The LLM interprets
  intent and never calculates.
- Dates resolve in the user's timezone from the injected clock.
- Every query is scoped by the authenticated user; another user's row is a 404.
- Every write records its audit event in the same database transaction.
- Domain modules never import `workflows`, `agents` or `llm`, and `finance_core` never imports
  FastAPI. A new domain module joins the import-linter contract in `pyproject.toml`.

## Changing things safely

- **Schema**: add an Alembic revision chained onto the single current head (`uv run alembic
  heads`, run in `backend/`, prints one line), then `uv run alembic check` reports no drift.
- **API**: run `npm run contracts` and commit `packages/contracts/`; CI fails on drift.
- **Prompts**: a change is a new versioned file in `llm/prompts/`, measured with the live eval
  over repeated runs (`RUN_LIVE_LLM=1`); a single request proves nothing. The context block
  stays at the top of the understand prompt.
- **Tests**: integration tests drop and re-migrate the database in `TEST_DATABASE_URL` and flush
  the Redis db in `TEST_REDIS_URL`. Two test runs at the same time each need their own database
  and Redis db index.
- **Web**: `apps/web` runs a Next.js release newer than your training data; read
  `apps/web/AGENTS.md` before writing web code. Event streams need `Cache-Control:
  no-transform`; verify streaming against the built app, since `next dev` hides proxy buffering.
  Pages stay alive between client-side navigations (React `<Activity>`): state and refs survive
  and effects re-run when the page shows again, so a one-shot ref guard or reset-on-unmount
  logic breaks the second visit.
- **Commits on Windows**: write the message to a file and use `git commit -F <file>`.

## Agent skills

### Issue tracker

Local markdown: each feature is a directory under `.scratch/` with a `spec.md` and one file per
ticket in `issues/`. See `docs/agents/issue-tracker.md`.

### Triage labels

The five default roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`,
`wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `GLOSSARY.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
