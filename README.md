# MoneyMoney

A chat-first personal finance assistant. You type "spent 350 on groceries yesterday" and
it records the expense, asks a short follow-up question when something is missing, and
answers "how much did I spend this month?" from exact database totals, never from the
model's memory.

- **Web:** Next.js 16 + React 19 + Tailwind 4 (`apps/web`)
- **API:** FastAPI with server-sent-event chat turns (`apps/api`)
- **Core:** domain services, Postgres, Redis, LangGraph workflow, Gemini on Vertex AI
  (`backend`, the `finance-core` library shared by the API and the future MCP server)

Status: Phases 1 and 2 are built; the Phase 2 code review is next (see
[Roadmap](#roadmap)). See [docs/architecture.md](docs/architecture.md) for how it fits
together, and [docs/phase-1-report.md](docs/phase-1-report.md) and
[docs/phase-2-report.md](docs/phase-2-report.md) for the phase reports.

## What you can do

### Record and ask in chat

- Log expenses and income in plain words, several in one message: "350 on dinner yesterday
  via UPI and 120 for coffee".
- When something is missing or unclear, the assistant asks one short question with options
  (category, amount, date), and remembers the question across reloads.
- Ask "how much did I spend this month?" or "show my largest expenses last month". Totals are
  exact SQL sums in your timezone, never the model's arithmetic.
- **Merchant rules:** MoneyMoney learns which category you use for each merchant and files the
  next one the same way. A category you pick or name always wins: "If you pick or name a
  category, I use it; otherwise I use what you used last time for that merchant; otherwise I
  guess, or ask."

### Split with friends

- Keep a **Friends** list (a name and an optional email). A friend who uses MoneyMoney gets an
  invite and, once they accept, is linked.
- Split a bill in chat ("me and Jaymin spent 1000 on pizza, split it", "Jaymin paid 1200 for
  movie tickets, split it") or with Add transaction on the transactions page. Your share is
  what counts in your spending, not the whole bill.
- See who owes whom ("does Jaymin owe me?") and record a settlement ("Jaymin paid me 500").
  A settlement is never income or spending.
- A linked friend gets their share in their own records straight away and sees a "Shared with
  you" card the next time they open the app. They see only that shared expense.

### Manage your records

- Transactions page: search, filter, edit (safe against two tabs editing at once), delete
  and restore. A running monthly tally sits above the chat.
- **Accounts:** add your bank accounts, credit cards, wallets and cash in Settings; rename,
  re-kind or archive them. Tag an expense or income with one ("paid 300 for lunch from HDFC")
  and filter the transactions page by account.
- **Transfers:** move money between your own accounts, in chat ("moved 5000 from HDFC to
  Paytm", "withdrew 2000 from SBI", "paid the credit card bill from HDFC") or with Add
  transaction on the transactions page. A transfer is never income or expense, so it stays out
  of every total.
- **Merchant rules** in Settings: see what was learned, change a rule's category, or forget it.

### Your login

- **Security** in Settings: see every signed-in device, sign one out or all the others, and
  change your password.
- **Forgot password?** on the login page emails a single-use link that works for 30 minutes
  and signs you out everywhere. Until an email provider is chosen, the email is printed in the
  API log (see [Finding a password reset link locally](#finding-a-password-reset-link-locally)).
- **Appearance:** light, dark, or follow your device.

### Built to be trusted with money

- Money is stored as exact integer minor units; amounts with more precision than a currency
  allows are rejected, never rounded.
- Retries never create duplicates, every change is audited, and one user can never see
  another's data.
- If Gemini is slow or down, the offline parser answers instead of failing the turn.

## Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| 1 | Chat entry with clarifications, transaction history, exact summaries, auth and isolation, Gemini + offline parser, tests, containers, CI | Done |
| 2 | Merchant rules, accounts, transfers, account security, dark mode | Done |
| 3 | Split expenses with friends, Splitwise-style: "me and Jaymin spent 1000 on pizza, split it"; who owes whom, settling up, and the friend sees it in their own records | Done |
| 4 | Imports: CSV and Excel first, then receipts and PDF bank statements | In progress |
| 5 | Charts and insights; a policy for totals across currencies | Planned |
| 6 | Voice and Indian languages (Gujarati, Hinglish, lakh/crore), debt and credit-card bill tracking | Planned |
| 7 | MCP server over the same domain services (OAuth 2.1, confirmation before writes) | Planned |

Phase 2 in detail:

- Built: merchant rules (learn, apply, view/change/forget in Settings), accounts, tagging
  transactions with an account (on the page and in chat), transfers (on the page and in
  chat), security settings (devices, change password), "Forgot password?" with an emailed
  reset link (printed in the API log until an email provider is chosen), and dark mode.
- Next: a code review of the whole branch, then merging it into `main`.
- Deliberately later: account balances, transfers between currencies, a real email provider,
  two-factor sign-in, data export and account deletion.

The Phase 2 plan, its spec and tickets live in [`.scratch/phase-2/`](.scratch/phase-2/).

Phase 3 in detail:

- Built: a friends list with invites, shared expenses (equal or exact split, the user or a
  friend as payer), balances per currency, settlements, "Shared with you" notices for linked
  friends, and all of it in chat (prompt `understand_v4`).
- Next: a code review of the whole branch, then merging it into `main`.
- Deliberately later: groups, percentage splits, currency conversion, push or email notices.
  See the [Phase 3 report](docs/phase-3-report.md) for the known limitations.

The Phase 3 plan, its spec and tickets live in [`.scratch/phase-3/`](.scratch/phase-3/).

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
| `backend/src/finance_core/` | Domain services (auth, users, accounts, categories, merchants, friends, transactions, reports, conversations, audit), database, Redis helpers, LLM layer, LangGraph workflow, agent runtime |
| `backend/migrations/` | Alembic migrations (the only place schema changes happen) |
| `apps/api/src/finance_api/` | FastAPI app: routes, dependencies, security, error envelope, middleware |
| `apps/web/` | Next.js app: chat, transactions, friends, settings |
| `packages/contracts/` | `openapi.json` exported from the API and the TypeScript types generated from it |
| `tests/` | `unit/`, `integration/` (real Postgres + Redis), `evals/` (LLM understanding cases) |
| `infrastructure/local/` | Docker Compose init scripts |
| `docs/` | Architecture, progress log, phase reports |
| `.scratch/` | Feature specs and tickets (the local issue tracker) |
| `CLAUDE.md`, `GLOSSARY.md` | Coding standards for contributors and agents; the domain vocabulary |

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
| `WEB_BASE_URL` | `http://localhost:3000` | Where the web app is served; password reset links point here |
| `RATE_LIMIT_PASSWORD_RESET_PER_EMAIL_PER_HOUR` | `5` | Reset emails per address per hour (counted even when no account exists, so the limit reveals nothing) |
| `RATE_LIMIT_PASSWORD_RESET_PER_IP_PER_HOUR` | `20` | Reset requests per client IP per hour |
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

### Finding a password reset link locally

No email provider is configured yet. The only email sender is a console sender: outside
`ENVIRONMENT=production` it writes the whole email, link included, to the API log, and in
production it sends nothing and logs a warning without the link.

1. On the login page, choose **Forgot password?** and submit the email of an existing account.
   The page says the same thing whether or not the account exists.
2. Read the API log: the terminal running `npm run dev:api`, or `docker compose logs api` for
   the containers. Look for "email printed here instead of sent", then the line
   `http://localhost:3000/reset-password#token=…` (it uses `WEB_BASE_URL`). `.env.example` sets
   `LOG_JSON=false`, which keeps the log readable.
3. Open the link within 30 minutes. It works once; using it signs out every device.

## API endpoints added in Phase 2

All are under `/api/v1` and described in the OpenAPI document. Everything except the two
`password-reset` routes needs a signed-in user, and another user's id is a 404.

| Endpoint | Does |
| --- | --- |
| `GET /merchant-rules` | List what MoneyMoney learned (filters `type`, `q`; most recently used first) |
| `PATCH /merchant-rules/{id}` | Change a rule's category |
| `DELETE /merchant-rules/{id}` | Forget a rule |
| `GET /accounts` | List accounts (`includeArchived`, default false) |
| `POST /accounts` | Add an account (name, kind, currency; 409 if the active name exists) |
| `PATCH /accounts/{id}` | Rename, change kind, archive or unarchive |
| `GET /transactions?accountId=` | Filter by account (either end of a transfer) |
| `POST /transactions`, `PATCH /transactions/{id}` | Now accept `accountId`, and for `type: "transfer"` also `toAccountId` |
| `GET /auth/sessions` | List signed-in devices |
| `DELETE /auth/sessions/{id}` | Sign one device out |
| `POST /auth/sessions/revoke-others` | Sign out every other device |
| `POST /auth/password` | Change password (needs the current one; signs out other devices) |
| `POST /auth/password-reset` | Ask for a reset link (always 202) |
| `POST /auth/password-reset/confirm` | Choose a new password with the link's token (204; 422 `reset_link_invalid`) |

## API endpoints added in Phase 3

All are under `/api/v1`, need a signed-in user, and another user's id is a 404.

| Endpoint | Does |
| --- | --- |
| `GET /friends` | List friends with their balances per currency (zero balances left out) |
| `POST /friends` | Add a friend (name, optional email); an email that belongs to a user sends an invite |
| `GET /friends/{id}` | One friend with balances and every shared expense and settlement between you |
| `PATCH /friends/{id}` | Rename or change the email (409 `friend_linked` for a linked friend's email) |
| `DELETE /friends/{id}` | Remove a friend; one with shared history is archived instead |
| `GET /friend-invites` | Invites waiting for your answer |
| `POST /friend-invites/{id}/accept` | Accept: you and the sender are now linked friends |
| `POST /friend-invites/{id}/decline` | Decline (204) |
| `GET /shared-expenses` | List shared expenses you can see (as recorder or participant) |
| `POST /shared-expenses` | Record one: total, currency, date, payer, split `equal` or `exact` and the friends |
| `GET /shared-expenses/{id}` | The total, payer and every share |
| `PUT /shared-expenses/{id}` | Replace the bill and split (recorder only) |
| `DELETE /shared-expenses/{id}` | Delete it for everyone; it cannot be restored |
| `GET /settlements` | List settlements (`friendId` filter) |
| `POST /settlements` | Record a settlement; larger than the balance saves with `exceedsBalance: true` and a warning |
| `DELETE /settlements/{id}` | Delete a settlement |
| `GET /notices` | The "Shared with you" notices |
| `POST /notices/read` | Mark notices as read |
| `GET /transactions` | The list now carries `sharedExpenseId` on a share. A share's amount, date and type change only through the shared expense (409 `shared_expense_locked`) |

### Trying sharing locally with two users

1. Start the app (see [Quick start](#quick-start)) and register two users, for example
   `riya@example.com` and `jaymin@example.com`, in two different browsers (or one normal and
   one private window), because a session is per browser.
2. As Riya, open **Friends** and add "Jaymin" with the email `jaymin@example.com`.
3. As Jaymin, open **Friends**, find Riya's invite and press Accept. They are now linked.
4. As Riya, in chat: "me and Jaymin spent 1000 on pizza, split it". Save it. Riya's
   transactions show a share of 500, and Friends shows "Jaymin owes you 500".
5. As Jaymin, open the app: the "Shared with you" card shows the pizza, and his transactions
   hold his own 500 share.
6. As Riya: "Jaymin paid me 500". The balance goes to zero and Jaymin gets a notice. Neither
   side's income changes.

To try it with one user, add a friend with no email: it works the same, without the invite and
without the friend's side.

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

588 tests pass today (plus one skipped: the opt-in live eval).

- **Unit:** money, dates and periods, reconciliation, workflow logic, category precedence,
  merchant keys, device labels, transfer and "paid from" phrasing, the console email sender,
  error mapping. These need no services.
- **Integration:** run against a separate `moneymoney_test` database and Redis db 1. They
  cover auth, sessions and password changes, user isolation, idempotency, optimistic locking,
  cache invalidation, merchant rules, accounts, transfers, password reset, friends and invites, shared expenses, balances and settlements, notices, a Redis outage, clarify/resume, a restart
  mid-question, double-texting, a Gemini outage, crash recovery and SSE. Locally they skip if
  the services are down; in CI they fail. Point `TEST_DATABASE_URL` / `TEST_REDIS_URL`
  elsewhere to run two suites side by side.
- **LLM eval (opt-in, calls Gemini):**
  `RUN_LIVE_LLM=1 uv run pytest tests/unit/test_understanding_eval.py -s`. Use repeated
  runs when comparing models, because a single run is noisy.

## Deployment

The target is Google Cloud: Cloud Run (web, API, migration job), Cloud SQL for
PostgreSQL, Memorystore for Redis, Vertex AI, and Secret Manager. Assumptions, required
settings and the scaling plan are in
[docs/architecture.md § Deployment](docs/architecture.md#deployment-on-google-cloud).
Infrastructure-as-code is not written yet (`infrastructure/gcp/` is empty).
