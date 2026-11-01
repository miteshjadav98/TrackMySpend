# Architecture

How MoneyMoney is put together, why it is shaped this way, and what has to be true to run
it in production. For setup and commands, see the [README](../README.md).

## Shape and sizing

MoneyMoney is a **modular monolith**. There is one Python core library, one API service, and
one web app, backed by one Postgres database and one Redis instance.

This matches the expected load. A personal finance app with up to around 100K users sees
tens of requests per second at peak. Most of those are small writes and reads scoped to one
user, and the expensive part is the LLM call, not the database. One well-indexed Postgres
handles that comfortably, so microservices would add network hops, retries and deploys
without solving a problem we have.

Financial correctness pushes the bar up, though. Even at low traffic, money must be exact,
saves must be idempotent, every change needs an audit trail, and one user must never see
another user's data. Those requirements shape most of the decisions below.

The seams for growth are already in place. Domain services know nothing about HTTP or the
LLM, so an MCP server (Phase 6) or a background worker can reuse them unchanged.

## Components

```mermaid
flowchart LR
    browser["Browser"] -->|"HTTPS, same origin"| web["Next.js web app<br/>apps/web"]
    web -->|"/api/* rewrite<br/>(load balancer path rule in prod)"| api["FastAPI<br/>apps/api"]
    api --> core["finance-core<br/>domain services + agent"]
    core --> pg[("PostgreSQL<br/>identity · ledger · chat · audit · agent")]
    core --> redis[("Redis<br/>cache · rate limits · locks")]
    core --> gemini["Gemini on Vertex AI"]
    mcp["MCP server (Phase 6)"] -.-> core
    jobs["Jobs: migrate, prune-checkpoints"] --> core
```

- **Postgres is the only source of truth.** It holds financial records, chat transcripts,
  the audit log and workflow checkpoints.
- **Redis is never authoritative.** If it disappears, the app gets slower and less
  protected, but it stays correct (see [Failure behaviour](#failure-behaviour)).
- **The browser only talks to the web origin.** `/api/*` is forwarded to FastAPI, so the
  session cookie is first-party and there is no cross-origin surface.

## Code boundaries

```text
apps/api/finance_api        HTTP only: routing, auth dependencies, error envelope, SSE
        │
backend/finance_core
  ├── agents/               chat turn lifecycle, LangGraph runtime, checkpointer, retention
  ├── workflows/            the graph: nodes, state, drafts, questions, reconciliation
  ├── llm/                  provider-neutral client, Gemini, rules engine, resilience
  ├── transactions/ accounts/ merchants/ reports/ categories/ users/ auth/ conversations/ audit/
  │                         domain services (no HTTP, no LLM, no LangGraph)
  ├── email_sender.py       the EmailSender interface and the console sender
  ├── cache/ database/ observability/
  └── money.py dates.py ids.py clock.py errors.py config.py
```

import-linter enforces two rules in CI:

1. `finance_core` never imports `finance_api`, FastAPI or Starlette.
2. Domain services never import the workflow, agent or LLM layers.

So every capability is an ordinary async service method that takes a `UserContext`. REST
routes, graph nodes and future MCP tools all call the same methods, and authorization lives
in one place.

## Data model

Five Postgres schemas, each owned by one module:

| Schema | Tables | Notes |
| --- | --- | --- |
| `identity` | `users`, `financial_profiles`, `auth_sessions`, `password_reset_tokens` | Profile holds base currency, timezone and locale. Sessions and reset links store a SHA-256 of the token, never the token itself |
| `ledger` | `categories`, `transactions`, `accounts`, `merchant_rules` | 23 system categories are seeded with deterministic ids. Users can add their own. See [Merchant rules](#merchant-rules) and [Accounts and transfers](#accounts-and-transfers) |
| `chat` | `conversations`, `messages` | The transcript, including the structured UI each assistant message rendered |
| `audit` | `audit_events` | Written in the same database transaction as the change it records |
| `agent` | LangGraph checkpoint tables | Working memory for unfinished turns. Safe to prune |

Conventions:

- **Ids** are UUIDv7: time-ordered, so inserts stay index-friendly, and they are safe to
  expose.
- **Money** is an integer in minor units (`amount_minor`) plus an ISO 4217 `currency`.
  Precision comes from an exponent table (JPY 0, INR 2, KWD 3). Input with more precision
  than the currency allows is rejected, never rounded. Formatting (₹1,23,456.78) happens at
  the edge, using Babel.
- **Dates:** a transaction stores `occurred_on DATE` in the user's own calendar. "Today",
  "last month" and "this week" resolve deterministically in the user's timezone, from an
  injected clock, so tests can pin time.
- **Transactions:** the type is `expense`, `income` or `transfer`. A row is soft-deleted
  (`deleted_at`) and can be restored. It carries an optimistic-lock `version`, a `source`
  (chat, manual, import or api) and an optional `source_ref` pointing at the chat message
  that created it.
- **Accounts:** an `accounts` row has a name (1-60 characters), a kind (`bank`,
  `credit_card`, `wallet`, `cash`, `other`), a currency that is fixed after creation, and an
  archived flag. Names are unique per user, ignoring case, among active accounts only (a
  partial unique index), and a user has at most 50 active accounts. Accounts are archived,
  never deleted.
- **Transaction accounts:** `transactions.account_id` is optional on an expense or income
  (where the money left, or arrived) and `to_account_id` is set only on a transfer. Check
  constraints in the database hold the rules: a destination account only on a transfer, and
  a transfer has both accounts, different from each other, and no category. These two
  columns and the category reference use the default `NO ACTION`, so a later cascading user
  deletion still works.
- **Merchant rules:** one `merchant_rules` row per (user, type, merchant key): the
  merchant's latest spelling, the category, a use count and when it was last used. The
  merchant key is the name case-folded, with punctuation removed and spaces collapsed, so
  "SWIGGY" and "Swiggy!" are one rule. Expense and income rules are kept apart.
- **Reset tokens:** `identity.password_reset_tokens` holds the SHA-256 of a reset token, its
  expiry (30 minutes), when it was used and the requesting IP. The token itself is never
  stored.
- **Idempotency:** `UNIQUE (user_id, idempotency_key)` with
  `INSERT … ON CONFLICT DO NOTHING`, then the existing row is returned. A retry returns
  200 with the original row instead of creating a duplicate.
- **Hot-path index:** `(user_id, occurred_on DESC, id DESC) WHERE deleted_at IS NULL`. It
  serves listing, keyset pagination and the period sums behind every summary.

## A chat turn, end to end

```mermaid
sequenceDiagram
    participant B as Browser
    participant A as FastAPI
    participant C as ChatService
    participant G as LangGraph (finance-v1)
    participant P as Postgres
    participant L as Gemini

    B->>A: POST /conversations/{id}/messages/stream {clientMessageId, input}
    A->>C: prepare()
    C->>P: ownership · replay check (clientMessageId) · crash recovery
    C->>C: rate limits · per-conversation lock · validate answer vs pending question
    C->>P: save user message
    A-->>B: 200 text/event-stream: turn.started
    A->>C: execute() in its own task
    C->>G: run, or resume with Command(resume=answer)
    G->>L: understand (structured output)
    G->>G: reconcile with rules engine, build drafts
    alt something is missing or ambiguous
        G-->>C: interrupt(question)
    else complete
        G->>P: save transactions (idempotent) + audit, same DB transaction
    end
    C->>P: save assistant message (text + UI)
    C-->>B: status · text.delta · interaction · turn.completed
```

What makes this robust:

- **All errors that can be known before streaming** (404, 409, 422, 429) are raised in
  `prepare()`, so they come back as proper HTTP statuses, not as events inside a 200
  stream.
- **The turn runs in its own task.** If the browser disconnects, the turn still
  finishes, and the reply is there on reload.
- **Retries are safe.** The client generates `clientMessageId` once per message and reuses
  it on retry. A finished turn is replayed as a single `turn.completed` event, never run
  twice.
- **One turn at a time per conversation.** A Redis lock prevents double-texting from racing
  the same workflow thread. A second concurrent message gets a 409.
- **Crash recovery:** if the graph finished but the process died before the transcript
  write, the checkpoint's `last_message_id` lets the next request detect this and recover.
- **Streaming survives proxies.** Event streams send
  `Cache-Control: no-store, no-transform`, which stops proxies (including Next.js's gzip
  on the rewrite) from buffering them.

Event types (`TurnEvent` in the OpenAPI document): `turn.started`, `status`, `text.delta`,
`interaction`, `turn.completed`, `error`. Interactions are typed UI payloads:
`clarification`, `confirmation`, `transactions_saved`, `summary`, `transaction_list` and
`suggestions`. The web app renders each one as a card. Answers come back as
`{"type": "interaction_response", …}` and are validated against the pending question
before the workflow resumes.

## The workflow

```text
START -> understand --+--> prepare_record <--> clarify (interrupt)
                      |         |                 |
                      |         +--> save --------+--> respond -> END
                      +--> summarize ----------------> respond
                      +--> search -------------------> respond
                      +------------------------------> respond
```

**State rules** (`workflows/state.py`):

- State holds plain JSON values only. Checkpoints stay small, deserialisation runs in
  strict mode (`allowed_msgpack_modules=None`), and schema evolution is just "read with
  defaults".
- Every key has exactly one writer per step, so the state needs no reducers.
- Identity (user, conversation, timezone, today's date) lives in `TurnContext`, LangGraph's
  `context_schema`, never in state. A node cannot change who it acts for, and identity is
  not copied into every checkpoint.

**Checkpointing and durability.** An `AsyncPostgresSaver` writes to the `agent` schema
with `durability="exit"`, which means one checkpoint write per turn instead of one per
step.

This is safe because the only side effect, saving transactions, is idempotent:

- Draft ids are derived deterministically from `(message_id, index)`.
- `save` checks `source_ref` before inserting.

If a process dies mid-turn, the retry re-runs the turn from the last checkpoint and lands on
the same rows.

**Clarification** uses `interrupt()`. Rounds are bounded (`AGENT_MAX_CLARIFICATION_ROUNDS`,
5), and a pending question expires after `AGENT_PENDING_TTL_HOURS` (24). If the user types
something unrelated instead of answering, the draft is abandoned explicitly rather than
being silently guessed.

**Versioning.** Node names and state keys are persisted, so renaming one is a migration:

1. Bump `GRAPH_VERSION`.
2. Route new threads to the new graph.
3. Let old threads drain.

**Retention.** Checkpoints are working memory, not records: the transcript is in
`chat.messages` and the money is in the ledger. `manage prune-checkpoints` drops threads
inactive for 30 days, and should be scheduled daily.

## Merchant rules

MoneyMoney remembers the category you use for each merchant (`merchants/`).

- **Learning** happens in `TransactionService`, in the same database transaction as the
  save, so every path teaches: a chat save, `POST /transactions`, and a `PATCH` that
  changes the category or the merchant. It upserts the rule for (type, merchant key) and
  bumps its use count. Only a newly inserted row teaches, so an idempotent replay teaches
  nothing. Nothing is learned from a transaction with no merchant, from a transfer, or from
  the fallback categories ("Other", "Other income"), so "I don't know" never becomes a rule.
- **Category precedence** for a chat draft (`workflows/category_choice.py`), highest first:
  1. a category you picked in a clarification;
  2. a category you named in the message (the model's suggested category counts as named
     when its name, or a distinctive word of it, appears as a whole word in your message);
  3. the merchant rule;
  4. the model's suggested category;
  5. otherwise, a clarification.

  In one sentence: if you pick or name a category, I use it; otherwise I use what you used
  last time for that merchant; otherwise I guess, or ask. The draft records which level
  chose the category (`category_source`), so the reply can say "Filed under Office meals, as
  before for Swiggy." A rule whose category is archived is ignored.
- **A guess is learned only for a new merchant.** A rule outranks the model's guess, so a
  guess can only become a rule for a merchant that had none, and a correction always wins.
- **Settings** use `GET /api/v1/merchant-rules` (filters `type` and `q`, most recently used
  first, keyset pagination), `PATCH /api/v1/merchant-rules/{id}` to change the category (not
  to "Other" or "Other income": forget the rule instead) and `DELETE` to forget it. Forgetting
  does not switch learning off: the next save for that merchant teaches a new rule. Changing
  and forgetting are audited (`merchant_rule.changed`, `merchant_rule.forgotten`); automatic
  learning is not, because the save that caused it already is.

## Accounts and transfers

- **Accounts** are managed with `GET`, `POST` and `PATCH /api/v1/accounts`. The list is not
  paginated (50 active accounts at most), shows active accounts first and then by name, and
  `includeArchived=true` adds the archived ones. A duplicate active name is 409
  `account_exists`; the limit or an unsupported currency is 422. There is no delete. An
  archived account stays on its past transactions but cannot be picked for new ones.
- **Tagging.** An expense or income may carry an account, even one in another currency (a
  card used abroad). The transactions list filters on `accountId`, which matches either end
  of a transfer.
- **Transfers** are `type: "transfer"` on the normal transaction endpoints. `accountId`
  (from) and `toAccountId` (to) are required and must differ, there is no category, and the
  amount's currency must equal both accounts' currency. There is no currency conversion.
  Errors name the field: `accountId`, `toAccountId`, `categoryId` or `currency`. Changing a
  transaction's type clears the fields that no longer apply, and the result must satisfy
  the new type's rules or the edit is a 422.
- **Reports.** Summaries, category totals and the monthly tally leave transfers out of
  income and expense; tests pin that.

### Shared expenses in chat

- Each extracted transaction can carry `participants` (the friends, as named, never the
  user), `payer` (a friend's name, else null for the user), `split` (`equal` or `exact`) and
  `shares` (what each person had, the user as "me"). The offline parser (`llm/sharing.py`)
  reads "me and X spent N on Y, split it", "X paid N for Y, split it", "me, X and Z spent N",
  and "dinner N with X, I had A and he had B".
- The draft keeps one `DraftPerson` per friend. Names resolve like account names
  (`friends/names.py`): exact ignoring case, else word containment. Several matches ask which
  friend (options show emails); no match asks "Add X as a new friend?", and the friend is
  created at save only if the user agreed. A friend who paid can only share with the user,
  so more people ask the user to narrow it down. Exact amounts that do not add up ask again.
- Save goes through `SharedExpenseService.create`, keyed by the chat message in
  `source_ref`, so a retried message finds the share it already saved. The model never
  calculates a share: `friends/splits.py` does, and the save card shows its figures.

### Accounts and transfers in chat

- The understanding schema has `transfer` as a type and two fields on each transaction:
  `account` (the user's own account the money left, or arrived in for income, as they named
  it) and `toAccount` (for a transfer, where it went). The user's active account names go
  into the request beside the categories. This is `understand_v2.md`; v1 stays in the
  folder.
- **The offline parser** reads "transfer/transferred/moved X from A to B", "withdrew X (from
  A)" (to the cash account) and "paid X credit card bill (from A)" (to the credit card).
  "sent X from A to B" is a transfer only when both ends are named: "sent 500 to Ramesh"
  stays an expense, and an ordinary bill ("electricity bill 1200") stays an expense.
- **Names resolve** against the user's active accounts (`accounts/names.py`): an exact
  name, ignoring case, wins; otherwise the one account whose words contain the name's words
  or are contained in them ("HDFC" and "HDFC Savings"); a bare kind ("cash") means the only
  account of that kind. Several matches, or none, lead to a clarification.
- **A transfer draft** has no category, merchant or payment method. Its clarifications come
  in this order: amount, amount confirmation, currency, from account, to account, date. The
  account questions offer the user's active accounts, most used first, and accept a typed
  new name. A new account is created at save, in the base currency, with its kind guessed
  from the name: "cash" is cash; "credit" or "card" is a credit card ("debit" is a bank);
  Paytm, PhonePe, GPay, Amazon Pay, MobiKwik and "wallet" are wallets; anything else is a
  bank. Choosing the same account for both ends asks again.
- **Expenses and income** are tagged with an account only when the user names one that
  resolves to exactly one active account. The assistant never asks about accounts for them.
  A name that matches none or several is left untagged, and the reply says "I couldn't
  match “X” to one of your accounts, so I saved it without an account." A "from X" or
  "into X" phrase that names one of the user's accounts is the account, not the merchant
  (reconciliation repairs this after the model); "from Nike" stays a merchant.
- **Replies** show "HDFC → Paytm Wallet" for a transfer and "from HDFC" ("into HDFC" for
  income) for a tagged transaction. Chat search accepts transfers as a type, and chat
  summaries keep leaving them out.

## Understanding messages (LLM layer)

- `LLMClient` is a two-method protocol: `understand()` returns structured output, and
  `stream_reply()` returns text. Gemini and the offline rules engine both implement it.
- **Gemini:** `gemini-3.5-flash-lite` with thinking level `low`, using JSON-schema
  structured output. Prompts are versioned files (`llm/prompts/`), and the version is
  logged with every call. The understand prompt is `understand_v3` (shared expenses,
  with the user's friend names in the context block); `understand_v1` and `understand_v2`
  stay beside it.
- **Reconciliation** (`workflows/reconcile.py`): the model's output is merged with the
  deterministic rules parse. This step:
  - fills gaps
  - merges split fragments
  - drops duplicate drafts
  - resolves relative dates in code
  - maps a "fallback" category to *unknown*, so the user is asked instead of a category
    being invented
- **Guards:** an amount the model inferred, rather than read from the text, must be
  confirmed. Replies are checked so they never state a number the system did not compute.
- **Resilience:** per-attempt timeout, one retry, and a total budget of 20 s. After that,
  the turn falls back to the rules engine (`degraded: true` in the message metadata).
- **Why these settings:** they were chosen from the eval set (`tests/evals`, repeated live
  runs).

  | Setup | Accuracy | Latency | Verdict |
  | --- | --- | --- | --- |
  | flash-lite + `minimal` | 51% | | Rejected |
  | flash-lite + `low` | 87% | | |
  | flash-lite + `low` + reconciliation | 78/78 | p50 1.26 s, p90 1.65 s | Chosen |
  | 3.8-flash | 100% | 35 s tail | Rejected for chat |

  Prompt context must stay at the top of the prompt: moving it last made the model return
  nulls.

  `understand_v2` was measured the same way, over repeated live runs, and stayed at Phase 1
  accuracy with no latency regression (see the [Phase 2 report](phase-2-report.md)). One
  request proves nothing, so a prompt change is always judged over several runs.

The LLM interprets intent. It never calculates. Every total comes from SQL.

## Financial correctness

- **Totals are SQL sums** over live rows, grouped by currency, inside the period resolved
  in the user's timezone. Different currencies are never added together (there is no FX
  conversion yet). Transfers are excluded from income and expense, so paying a
  credit card bill from a bank account is not counted twice.
- **Every summary states its period and label** ("October 2026", 1–26 Oct), so the user can
  see exactly what was counted.
- **Edits use optimistic locking.** A stale `version` gets a 409, never a silent overwrite.
  Deletes are soft, with restore. Every create, update, delete and restore writes an
  audit event in the same database transaction.
- **Duplicates are prevented at three levels:** the client idempotency key, deterministic
  draft ids with a `source_ref` check, and a duplicate guard in reconciliation.

## Redis

| Use | Key idea | If Redis is down |
| --- | --- | --- |
| Summary cache | Key includes a per-user **data generation**, which every write bumps. Stale entries are never read; they simply expire | Computed from Postgres every time |
| Rate limits | Fixed window per user/IP (login, register, chat per minute and per day) | Fail open: availability wins, and the event is logged |
| Conversation lock | `SET NX` with a token; released only by its owner | Proceeds unlocked (logged). Saves are idempotent, so the worst case is a 409 later |

A circuit breaker stops the app from waiting on a dead Redis, and socket timeouts are
500 ms.

## Auth and security

- **Server-side sessions.** The client gets an opaque 256-bit token in the `mm_session`
  cookie (HttpOnly, SameSite=Lax, Secure in production) or as a Bearer token for API
  clients.
  - Only its SHA-256 is stored.
  - Expiry slides to 30 days with activity, capped at 90 days absolute.
  - Logging out revokes the session server-side, so it stops working immediately.
- **Signed-in devices** (Settings → Security). `GET /api/v1/auth/sessions` lists the user's
  active sessions with a device label ("Chrome on Windows", "API client"), IP address, last
  activity and `isCurrent`. `DELETE /api/v1/auth/sessions/{id}` signs one out (revoking the
  current one is a logout) and `POST /api/v1/auth/sessions/revoke-others` signs out all the
  rest. Another user's session id is a 404. The label comes from a small user-agent reader
  (`auth/devices.py`) with no extra dependency.
- **Changing the password** (`POST /api/v1/auth/password`) checks the current password and
  the password policy, and that the new one differs. It rehashes with Argon2id, signs out
  every other session and keeps this one. It is rate-limited like login, so a stolen
  session cannot be used to guess the password.
- **Passwords** use Argon2id, hashed in a worker thread behind a semaphore so that login
  bursts cannot starve the event loop.
- **Password reset** (`auth/password_reset.py`) emails a link to
  `<WEB_BASE_URL>/reset-password#token=…`; the token sits in the URL fragment, so it never
  reaches a server log or a Referer header.
  - The request always gets the same 202, and the account lookup and email happen after
    the reply, so neither its body nor its timing shows whether an account exists. It is
    rate-limited per email (hashed) and per IP.
  - Only the token's SHA-256 is stored. A link works once, for 30 minutes, and a newer
    link replaces it. One atomic UPDATE checks and claims it, so two uses cannot both win.
  - Using it (`POST /api/v1/auth/password-reset/confirm`) sets the password and signs out
    every session in one transaction. An unknown, used or expired link is 422
    `reset_link_invalid`.
  - Requests are `POST /api/v1/auth/password-reset`. The limits are
    `RATE_LIMIT_PASSWORD_RESET_PER_EMAIL_PER_HOUR` (5) and
    `RATE_LIMIT_PASSWORD_RESET_PER_IP_PER_HOUR` (20).
  - Email goes through `EmailSender` (`email_sender.py`). Until a provider is chosen the
    console sender prints the email locally and, in production, sends nothing and never
    logs the link.
- **Audit.** Security events are audited: `auth.session_revoked`,
  `auth.other_sessions_revoked`, `auth.password_changed`, `auth.password_reset_requested`
  (only for existing accounts) and `auth.password_reset`.
- **Origin check.** Writes authenticated by cookie must come from an allowed origin. This is
  the CSRF defence alongside SameSite.
- **User isolation:** every query is scoped by the authenticated `user_id`. Integration
  tests assert that one user cannot read, change or even detect another user's data (404,
  not 403).
- **Logging:** request logs carry the method, path, status, duration and request id. Query
  strings and message text are never logged.
- **Security headers** (nosniff, frame DENY, referrer policy, HSTS when secure) are set on
  every response. API responses send `Cache-Control: no-store`.
- **Containers** run as non-root users. In the API image the code is owned by root and is
  read-only to the service user.

## API conventions

- Versioned under `/api/v1`, and documented by OpenAPI. In TypeScript, response fields are
  always required (null when absent), so the web app never has to guess whether a field
  might be missing.
- **Error envelope everywhere:** `{"error": {"code", "message", "requestId", "details"}}`.
  Validation errors never echo submitted values. A database outage returns 503 with
  `Retry-After`.
- `X-Request-ID` is accepted (or derived from Google's trace header) and returned on every
  response.
- Lists use keyset pagination (`cursor`), not offsets.
- `POST /transactions` accepts an `Idempotency-Key` header.
- **Health:** `/healthz` reports liveness without touching dependencies. `/readyz` requires
  Postgres; when Redis is down it still returns 200 but reports `degraded`.

## Web app

- Next.js 16 (App Router, Cache Components, partial prerendering) with React 19 and
  Tailwind 4. Server state lives in TanStack Query.
- API calls use `openapi-fetch` with types generated from the OpenAPI document, so a
  contract change shows up as a compile error.
- `proxy.ts` only routes optimistically (signed-out visitors go to `/login`). The API
  remains the authority on every request.
- Settings is a stack of independent sections sharing one frame: Profile, Appearance,
  Accounts, Merchant rules and Security. The signed-out pages `/forgot-password` and
  `/reset-password` serve the reset flow.
- The transactions page has an account filter and a type filter that includes transfers. Its
  add/edit dialog shows From account and To account when the type is Transfer.
- The chat view consumes the SSE stream and renders typed interaction cards. A running
  "tally" strip shows this month's totals and refreshes after each save.

## Failure behaviour

| What fails | What the user sees | Mechanism |
| --- | --- | --- |
| Gemini slow or down | Normal reply, from the rules engine | Timeout plus total budget, then fallback. `degraded` is logged |
| Redis down | Everything works, slightly slower | Fail-open cache, limits and locks. `/readyz` reports degraded |
| Postgres down | "Can't reach your records" (503, retry) | Error envelope with `Retry-After`. `/readyz` returns 503 |
| Browser drops mid-turn | Reply appears on reload | Turn runs in its own task. The transcript is persisted |
| Client retries a message | Same result, no duplicate | `clientMessageId` replay, idempotent saves |
| Process crash mid-turn | Next message recovers the turn | Checkpoint `last_message_id` plus idempotent save |
| Two tabs send at once | The second gets "busy, try again" (409) | Per-conversation lock |
| Turn exceeds 60 s | Retryable error event | `AGENT_TURN_TIMEOUT_SECONDS` |

Integration tests cover the Gemini, Redis, retry, crash and two-tab rows. The Postgres row
is tested at the error-mapping level. The disconnect and timeout rows are not tested yet.

## Deployment on Google Cloud

The target layout. Infrastructure-as-code is not written yet; this section is the
specification for it.

| Piece | Service | Notes |
| --- | --- | --- |
| Web | Cloud Run service (`apps/web` image) | Stateless, scales on requests |
| API | Cloud Run service (`apps/api` image) | `ENVIRONMENT=production`, `LOG_JSON=true`, `COOKIE_SECURE=true` |
| Migrations | Cloud Run Job, same API image, `python -m finance_core.manage migrate` | Runs before each API rollout. Expand/contract migrations only, so the old version keeps working |
| Retention | Cloud Scheduler → Cloud Run Job, `manage prune-checkpoints` | Daily |
| Routing | External HTTPS load balancer: `/api/*` → API, everything else → web | Keeps one origin for cookies. Set `FORWARDED_ALLOW_IPS` to the LB ranges, never `*` on a public service |
| Database | Cloud SQL for PostgreSQL 17, private IP, automated backups + PITR | One regional instance; HA when downtime starts costing money |
| Cache | Memorystore for Redis 7.x, private | Basic tier is acceptable because Redis is never authoritative |
| LLM | Vertex AI | The API's service account needs `roles/aiplatform.user`. No key files: ADC comes from the service identity |
| Secrets | Secret Manager → Cloud Run env bindings | `DATABASE_URL`, `REDIS_URL` |
| Observability | Cloud Logging (JSON logs with request id and trace) + Cloud Monitoring | Alert on 5xx rate, p95 turn latency, `degraded` turns, Cloud SQL connections |

Settings that must be right in production:

- **`ALLOWED_ORIGINS`** must be the public origin, or every cookie write is rejected.
- **`WEB_BASE_URL`** must be the public web origin, or reset links point elsewhere.
- **The connection budget.** Each API instance uses at most
  `DATABASE_POOL_SIZE + DATABASE_MAX_OVERFLOW + CHECKPOINT_POOL_MAX_SIZE` connections
  (10 + 5 + 5 = 20 by default). Cloud Run `max-instances × 20` must stay below Cloud SQL's
  `max_connections` with headroom. When it does not, enable Cloud SQL managed connection
  pooling (transaction mode) and keep `DATABASE_PREPARED_STATEMENTS=false`.
- **Behind a pooler, connection startup options may be rejected.** The API currently sets
  `search_path` (checkpointer) and `statement_timeout` as startup options. Behind a pooler,
  set them on the database role instead:
  `ALTER ROLE … SET search_path = agent, public; ALTER ROLE … SET statement_timeout = '5s'`.
- **Concurrency.** Cloud Run concurrency of around 40 per API instance suits a workload
  that mostly waits on the LLM. A turn holds a database connection only while it is
  reading or writing, not while it waits for Gemini.

## Scale plan

Where the system bends first, and what to do about it:

1. **LLM latency and quota.** This is the first bottleneck by far.
   - Watch: p95 turn latency, Vertex 429s, `degraded` turns.
   - Do: request a quota increase, shorten prompts (`understand` currently uses about
     2.7K input tokens), and route easy messages to the rules engine first.
2. **Database connections.** This comes before CPU.
   - Watch: Cloud SQL connections, pool wait time.
   - Do: managed connection pooling, then read replicas for summaries and search.
3. **Summary queries for heavy users.** The index already covers them.
   - Do, in order: rely on the generation cache, then a monthly rollup table maintained on
     write, then partitioning `ledger.transactions` by `user_id` hash. Only at that point
     consider sharding.
4. **Checkpoint table growth.** Retention handles this. If volume grows, partition by
   month or shorten the inactivity window.

## Deliberately not doing yet

| Not doing | Why | Trigger to revisit |
| --- | --- | --- |
| Microservices | One team, one deployable; distribution adds failure modes | Separate teams needing independent deploys, or one part needing very different scaling |
| Message queue / event bus | No asynchronous work yet | Phase 4 imports (long-running parsing), scheduled summaries |
| FX conversion | Totals per currency are exact; conversion needs a rate source and a policy | Users with multi-currency spending asking for a single total |
| Read replicas | One primary handles the load | Primary CPU above about 60% sustained, or summary queries above about 30% of load |
| Multi-region | 99.9% single-region is the target | Contractual availability above 99.95%, or users across continents |
| Account balances | Most transactions carry no account yet, so a balance would be wrong. Opening balances come with it | Imports (Phase 4) and debt tracking (Phase 7) put an account on most transactions |
| Cross-currency transfers | They need an exchange rate and a rule for which rate. Both accounts and the amount must share one currency | A decision on the multi-currency policy (Phase 5) |
| Email provider | Only the console sender exists: it prints the email in the API log outside production and sends nothing in production | Before real users need "Forgot password?" to work |
| Two-factor sign-in | Out of scope for Phase 2; sessions and password reset came first | After an email provider exists, or an authenticator-app option is chosen |
| Hand-made merchant rules | Rules are only learned from saves; there is no "never learn this merchant" switch | Users asking to teach or block a merchant |
| Other long-term memory | The profile covers timezone, currency and locale, and merchant rules cover categories | Reporting preferences or other learned habits |
| Infrastructure as code | No cloud environment yet | First staging deployment (Terraform in `infrastructure/gcp/`) |
