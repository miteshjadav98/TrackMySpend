# Phase 3 report

**Deliverable: MoneyMoney splits expenses with friends. You can record a shared expense, see who
owes whom, settle up, and a friend who also uses MoneyMoney gets their share in their own
records. Built and tested; the code review is still to come.**

Date: 2026-11-01 · Branch: `phase-3/integration` (not yet merged into `main`)

The plan is [`.scratch/phase-3/spec.md`](../.scratch/phase-3/spec.md) with 8 tickets in
`.scratch/phase-3/issues/`, and one decision record,
[ADR 0001](adr/0001-shares-are-each-users-own-expense.md). This report covers tickets 01 to 07
as built, and this ticket (08) as the documentation.

## Completed functionality

### Against the spec

| Spec area | Status | What it does | Ticket |
| --- | --- | --- | --- |
| Friends list and invites | Done | Add, rename, remove friends by name and optional email; an email that belongs to a user sends an in-app invite; accept, decline or cancel | 01 |
| Shared expenses | Done | Total, payer, equal or exact split, edit and delete, on `/api/v1/shared-expenses` and in the transactions page's Add transaction dialog; your share is an ordinary expense, so summaries need no change | 02 |
| Balances and settlements | Done | Balances per currency from one SQL query; Friends page with each friend's history; "Record settlement" form; settlements are never income or spending | 03 |
| The friend's side | Done | A linked friend's share lands in their own records at once, in their own category; the balance reads the same on both sides; past shared expenses come over when two users link | 04 |
| "Shared with you" notices | Done | In-app notices for shared expenses, settlements and invites, shown as a card on the chat and Friends pages and a badge on the Friends nav item | 05 |
| Shared expenses in chat | Done | "me and Jaymin spent 1000 on pizza, split it"; prompt `understand_v3` and the offline parser `llm/sharing.py` | 06 |
| Settlements and balances in chat | Done | "Jaymin paid me 500", "does Jaymin owe me?", "show my shared expenses"; prompt `understand_v4`, `settle` and `balances` workflow nodes, offline parser `llm/settling.py` | 07 |
| Docs and report | Done | README, architecture, glossary, this report, progress log | 08 |

### Decisions made while building

- **A share is an ordinary expense in each user's own records** (ADR 0001). The reason: every
  total in the codebase already adds up expenses, and a friend needs a row they can file and tag
  themselves. A share's amount, currency, date and type change only through the shared expense
  (409 `shared_expense_locked`).
- **Equal split, payer takes the leftover.** The payer handed over the whole amount, so the
  extra minor unit is theirs. When a friend paid, only you and that friend are participants.
- **Balances are per currency and computed in SQL**, with no conversion. A balance and a
  friend's history come from the same signed lines, so they cannot disagree.
- **Invites are matched by email**, so an invite for someone who has not signed up needs no hook
  at sign-up. A linked friend's email cannot be changed.
- **Linked friends' shares land straight away**, with no accept step. Notices tell them after.
- **Notices keep facts, not sentences.** The sentence is worded when it is read, so the amount
  follows the reader's locale. Notices are in-app only.
- **"I paid X N" is a settlement only in a narrow case:** X is one of your friends, no purpose
  is given ("for his old phone"), and the balance with X in that currency is not zero.
  Otherwise it is an expense with X as the merchant. "X paid me N" is always a settlement.
- **A chat save of a friend who is new** asks "Add X as a new friend?" and creates the friend
  only if you agreed.
- **Exact splits that do not add up** ask again ("Those add up to X, but the total is Y").

### Data and API added

- Migrations `0008` to `0011`: friends and invites, shared expenses and shares (plus
  `transactions.shared_expense_id`), settlements, notices.
- New endpoints are listed in the [README](../README.md#api-endpoints-added-in-phase-3), with
  a walk-through for trying sharing locally with two users.
- New web pages: Friends (`/friends`) and a friend's detail (`/friends/[id]`).
- New audit actions are recorded for every friend, invite, shared expense and settlement
  change, in the same database transaction as the change.

## Tests executed

| Check | Result |
| --- | --- |
| `uv run pytest` on this branch (unit + integration, real Postgres 17 + Redis 7.4) | **588 passed**, 1 skipped (the live LLM eval, opt-in), measured at the ticket 07 merge |
| Test count as tickets merged | 372 (01), 405 (02), 423 (03), 495 (06), 507 (04), 517 (05), 588 (07, final) |
| Phase 2 for comparison | 357 passed |
| `npm run check:api` (ruff, mypy `--strict`, import-linter), `alembic check`, `npm run contracts` | Clean at each ticket merge; Alembic has one head, `0011` |
| Web: typecheck, ESLint, production build | Clean at each ticket merge |
| Live LLM eval, `understand_v3` and `understand_v4` | See below |

Ticket 07 added 20 parser tests, 20 choice and reply tests and 17 chat integration tests, and
the merge added one more: a settlement recorded from chat is told to the linked friend. Every
new user-owned resource has an isolation test (another user gets a 404).

### Live eval numbers

Gemini on Vertex (`gemini-3.5-flash-lite`, thinking `low`) with reconcile. Every number comes
from five repeated runs of the whole case set, because one run proves nothing.

**Ticket 06, `understand_v3`: 38 cases (the 29 existing plus 9 shared-expense cases).**

| Run | Accuracy | p50 | p95 |
| --- | --- | --- | --- |
| 1 | 100% (38/38) | 1277 ms | 1625 ms |
| 2 | 100% | 1258 ms | 1490 ms |
| 3 | 100% | 1248 ms | 1494 ms |
| 4 | 100% | 1191 ms | 1521 ms |
| 5 | 100% | 1227 ms | 1475 ms |

**Ticket 07, `understand_v4`: 50 cases (the 38 above plus 12 settlement, balance and
negative cases).**

| Run | Accuracy | p50 | p95 |
| --- | --- | --- | --- |
| 1 | 100% (50/50) | 1388 ms | 2111 ms |
| 2 | 100% | 1400 ms | 1993 ms |
| 3 | 100% | 1326 ms | 1618 ms |
| 4 | 100% | 1368 ms | 1743 ms |
| 5 | 100% | 1342 ms | 1617 ms |

- The 12 new cases passed in all five runs (60 of 60). No provider errors.
- **Same-day comparison on the 38 older cases, five runs each.** v3: 97.4%, then 100% four
  times, p50 1246 / 1215 / 1201 / 1229 / 1236 ms. v4: 100%, 97.4%, then 100% three times, p50
  1408 / 1418 / 1340 / 1356 / 1366 ms. Same accuracy; **v4 is about 0.12 to 0.15 s slower at the
  median**, which fits the longer prompt. Each version showed one duplicated transaction in one
  run, the known miss that reconcile usually removes.
- For `understand_v3` against `understand_v2` on the 29 older cases (ticket 06): both 100% in
  every run, v3 about 0.1 s slower at the median.
- Against the Phase 1 baseline (p50 1.26 s) and Phase 2 (about 1.11 s), `understand_v4` is at
  about 1.37 s. That is a real latency cost of the added intents, with no loss of accuracy in
  these runs. The comparisons ran at different times, so the gap is indicative, not exact.

## Known limitations

### Product gaps

- **A friend cannot tag their own account on a settlement.** The `friend_account_id` column is
  read when a settlement is shown on the friend's side, but nothing sets it. Only the recorder
  can tag an account.
- **A settlement saved from chat has no idempotency key.** The `settle` node has no retry
  policy; it relies on the chat layer replaying a retried message id. A retry that reaches the
  node twice by another route could save it twice.
- **Deleting a shared expense is permanent.** It removes the bill, its shares and every
  participant's share transaction. The audit log keeps the snapshot, but nothing restores it.
  In chat, the save card's Undo deletes the whole shared expense the same way.
- **In a message that mixes shared and ordinary expenses, the ordinary ones are saved first**
  (as one batch), then each shared one through the shared-expense service. A reply lists them in
  the order you said them, but if a shared expense fails to save after that, the reply is a
  "couldn't save" outcome while the ordinary ones are already saved.
- **A friend name that is unknown or matches several friends gets a plain reply when settling**
  ("X paid me 500"): asking to add the friend, or to say the full name. It is not a question
  card, so you retype the message, and nothing is saved. "I paid X 500" with an unknown X is
  an expense with X as the merchant, by design.
- **`understand_v4` is about 0.13 s slower than v3** at the median (see the live eval).
- **No groups, percentage splits or currency conversion.** Each balance is per currency.
- **Notices are in-app only.** A friend who does not open the app is not told.
- **Linked friends' shares have no accept step.** They land at once; the friend can change the
  category, account and notes, but the amount, date and type follow the shared expense.
- **No account balances yet.** The full amount you paid for others is not a transaction, so an
  account's money would be wrong if balances existed (ADR 0001).
- A larger-than-balance settlement is saved with a warning, not refused.

### Quality and testing

- **Live eval noise.** Misses move from run to run, so a single run cannot show a regression.
  The case set is 50 English cases, still without Hinglish or Gujarati.
- The same-day v3 and v4 comparison is small (five runs of 38 cases each).
- No browser end-to-end tests: the web app is covered by typecheck, lint and the production
  build only, so the Friends page, the invite flow and the "Shared with you" card were not
  driven in a browser by the tests.
- The shares-sum rule is enforced in the service and the split arithmetic only. There is no
  deferred database check.
- Editing a shared expense is a full `PUT` with no version check, unlike transactions, so two
  edits at once are last-write-wins. No test covers it.

### Follow-ups recorded in the tickets

- `SharedExpenseService._create_share_transactions` and `_audit_all` were the seams for
  tickets 04 and 05 (ticket 02 and 04 comments); read them before changing delivery.
- The 50-active-account limit, the duplicated keyset-cursor helper and the hard-coded fallback
  slugs from Phase 2 are still open.

## Next steps

1. **Phase 3 code review** of the whole `phase-3/integration` branch, then fix what it finds
   in one fix-up ticket. It has not happened yet.
2. **Merge Phase 3 into `main`** after the review and the owner's OK. Phase 2 is also still
   waiting to merge.
3. **Decide the limitations above worth fixing next**, in this order of likely cost to a real
   user: undo for a deleted shared expense, an idempotency key on settlements, a friend's
   account tag on a settlement.
4. **Choose an email provider**, which both password reset and email notices wait for.
5. Later phases keep the order in the [README roadmap](../README.md#roadmap): imports
   (Phase 4), charts and a multi-currency policy (Phase 5), the MCP server (Phase 6), voice,
   Indian languages and debt tracking (Phase 7).
