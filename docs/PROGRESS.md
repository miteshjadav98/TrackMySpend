# Build progress

Living checklist for the Phase 1 build. Update it at each checkpoint commit.

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

## Next

1. Automated tests: unit (money, dates, rules, drafts/answers) and integration (auth, isolation,
   idempotency, cache invalidation, full chat flows incl. clarify/resume/restart).
2. Next.js web app + generated TypeScript contracts.
3. Dockerfiles, CI workflow, docs (README, architecture), PRD improvement suggestions.

## Resume

```powershell
docker compose up -d
uv sync --all-packages
cd backend; uv run alembic upgrade head
```
