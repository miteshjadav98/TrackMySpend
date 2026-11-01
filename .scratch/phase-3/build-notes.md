# Phase 3 build notes (shared briefing for implementer and merger subagents)

Repo: C:\Users\jadav\Videos\MoneyMoney. Integration branch: `phase-3/integration`.
Spec: `.scratch/phase-3/spec.md` (+ ADR `docs/adr/0001-shares-are-each-users-own-expense.md`, terms in `GLOSSARY.md`). Tickets: `.scratch/phase-3/issues/NN-*.md` (status line + checklist).
Tracker rules: `docs/agents/issue-tracker.md`. Repo rules: `CLAUDE.md` (read it: readable code,
money/date/audit rules, prompt versioning, contracts, Windows commits).

## Environment
- Postgres + Redis run in Docker (`docker compose up -d postgres redis`), already up.
- Each ticket has its own test database and Redis db, so parallel runs never collide:
  ticket NN -> `TEST_DATABASE_URL=postgresql://moneymoney:moneymoney@localhost:5432/moneymoney_test_tNN`
  (all ticket databases already exist), `TEST_REDIS_URL=redis://localhost:6379/<NN+1>`.
  Mergers use `moneymoney_test_merge` and Redis db 13. Create a missing database with
  `docker compose exec postgres createdb -U moneymoney <name>`.
- Commands (repo root): `npm run check:api`, `npm run test:api` (= `uv run pytest`),
  `npm run check:web`, `npm run build -w web`, `npm run contracts` (commit `packages/contracts/`).
  Schema: `uv run alembic heads` / `uv run alembic check`, run in `backend/`.
- Live eval: `RUN_LIVE_LLM=1 uv run pytest tests/unit/test_understanding_eval.py -m live_llm`.
  It needs `.env` (Gemini on Vertex, ADC credentials). Run it at least 5 times and record
  accuracy and latency (p50/p95) per run. Phase 1 baseline: 100% with reconcile, p50 1.26 s.
- Commits: git identity is not configured. Use
  `git -c user.name="Mitesh Jadav" -c user.email="miteshjadav.ict17@gmail.com" commit -F <file>`,
  with the message written to a file in this scratchpad. End messages with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push, never touch `main`.
- Shell edits with python heredocs mangle `\b` in regexes (it becomes a backspace). Use the
  Edit tool for regex code.

## Decisions already made (do not relitigate)
- Category precedence: picked in clarification > named in message > merchant rule > model guess > ask.
- Context block stays at the TOP of the understand prompt. Prompt changes are new versioned files.
- Transfers have no category, merchant or payment method; reports already exclude them;
  `MerchantRuleService.learn` already ignores a missing category.
- Single-request latency/accuracy checks prove nothing; always use repeated runs.
- Phase 3 decisions (spec): each share is an ordinary expense transaction in each user's own
  records (ADR 0001), so summaries need no change. Payer defaults to the user; equal split
  default; the payer's share takes leftover minor units. When a friend paid, only the user and
  that friend are participants. Balances per currency, computed in SQL. Settlements are not
  transactions. Linked friends' shares land straight away. Notices are in-app only.
- Implementer branches leave ticket files untouched except their own ticket's checklist and
  Comments; the merger sets Status to done and records the merge commit.
- The web app needs `node_modules`: in a worktree, run `npm install` (or `npm ci`) at the
  worktree root before `npm run check:web` / `npm run build -w web`.
