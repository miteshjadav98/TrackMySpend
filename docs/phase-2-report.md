# Phase 2 report

**Deliverable: MoneyMoney remembers how you file merchants, knows your accounts, records
transfers, and protects your login. Built and tested; the code review is still to come.**

Date: 2026-11-01 · Branch: `phase-2/integration` (not yet merged into `main`)

The plan is [`.scratch/phase-2/spec.md`](../.scratch/phase-2/spec.md) with 11 tickets in
`.scratch/phase-2/issues/`. This report covers tickets 01 to 10 as built, and this ticket (11)
as the documentation.

## Completed functionality

### Against the spec

| Spec area | Status | What it does | Ticket |
| --- | --- | --- | --- |
| Settings as sections | Done | One frame, five sections (Profile, Appearance, Accounts, Merchant rules, Security) | 01 |
| Merchant rules: learn and apply | Done | Every save teaches a rule; the next save for that merchant is filed by it; precedence is pick, name, rule, guess, ask | 02 |
| Accounts | Done | Add, rename, change kind, archive and unarchive in Settings; `GET/POST/PATCH /accounts` | 03 |
| Security: devices and password | Done | List devices, sign one or all others out, change password | 04 |
| Merchant rules in Settings | Done | List, search, change category, forget | 05 |
| Tag transactions with an account | Done | Account on expense and income, account filter on the transactions page | 06 |
| Forgot password | Done | Single-use 30-minute link, same reply for every email, console email sender | 07 |
| Transfers: API and page | Done | `type: "transfer"` with from and to accounts, shown as "HDFC → Paytm Wallet", left out of every total | 08 |
| Transfers in chat | Done | "moved 5000 from HDFC to Paytm", "withdrew 2000 from SBI", "paid 15000 credit card bill from HDFC"; prompt `understand_v2` | 09 |
| "Paid from" in chat | Done | "paid 300 for lunch from HDFC" is tagged with HDFC and "from HDFC" is not taken for a merchant | 10 |
| Docs and report | Done | README, architecture, glossary, this report, progress log | 11 |

Also built, outside the spec: a dark mode with a System / Light / Dark choice in Settings, and
a fix for `/chat` hanging on "Opening chat…" on a second visit (Next.js keeps pages alive in
React `<Activity>`, so a one-shot guard broke the second visit).

### Decisions made while building

- **Category precedence:** picked in a clarification, then named in the message, then the
  merchant rule, then the model's guess, then ask. The reply says when a rule chose
  ("Filed under Office meals, as before for Swiggy.").
- **Rules are never hand-made.** They are learned from saves; "Other" and "Other income" are
  never learned, and a rule cannot be changed to them (the API answers 422 "Forget the rule
  instead.").
- **`GET /accounts` is not paginated**, unlike other lists: a user has at most 50 active
  accounts, and the pickers need all of them.
- **The offline parser can be given the user's account names** so "from HDFC" is an account.
  Without a list it tags nothing.
- **Reconciliation repairs the model's output** for "from X" phrases: a merchant that is the
  account's own words is dropped, and a merchant after "from/into" that names one of the
  user's accounts becomes the account.

### Data and API added

- Migrations `0002` to `0007`: merchant rules, accounts, an index for rule listing, password
  reset tokens, transaction accounts, and transfers.
- New endpoints are listed in the [README](../README.md#api-endpoints-added-in-phase-2).
  New settings: `WEB_BASE_URL` and two reset rate limits.
- New audit actions: `merchant_rule.changed`, `merchant_rule.forgotten`, `account.created`,
  `account.updated`, `account.archived`, `account.unarchived`, `auth.session_revoked`,
  `auth.other_sessions_revoked`, `auth.password_changed`, `auth.password_reset_requested`,
  `auth.password_reset`.

## Tests executed

| Check | Result |
| --- | --- |
| `uv run pytest` on this branch (unit + integration, real Postgres 17 + Redis 7.4) | **332 passed**, 1 skipped (the live LLM eval, opt-in) |
| Test count as tickets merged | 164 (02), 193 (04), 203 (03), 211 (05), 253 (08), 332 (final) |
| Phase 1 for comparison | 142 passed |
| `npm run check:api` (ruff, mypy `--strict`, import-linter), `alembic check`, `npm run contracts` | Clean at each ticket merge |
| Web: typecheck, ESLint, production build | Clean at each ticket merge |
| Live LLM eval, `understand_v2` | See below |

The test count for 06, 07, 09 and 10 was not recorded in their tickets; the final count was
measured for this report with `TEST_DATABASE_URL` and `TEST_REDIS_URL` pointing at their own
database and Redis db.

Each new user-owned resource has an isolation test (another user gets a 404). The reset flow is
tested with a capturing email sender injected through the app factory, the way the LLM and the
clock are.

### Live eval numbers

Gemini on Vertex (`gemini-3.5-flash-lite`, thinking `low`) with reconcile. Every number comes
from repeated runs of the whole case set, because one run proves nothing.

**Ticket 09: 23 cases (13 from Phase 1, 10 new transfer cases), six runs.** Accuracy was 100%
in all six runs. Across all 138 calls, p50 was 1154 ms and p95 was 1486 ms. The Phase 1
baseline was 100% with p50 1.26 s.

**Ticket 10: 29 cases (the 23 above plus 6 new "paid from" and "into" cases), ten runs.**

| Run | Accuracy | p50 | p95 | Notes |
| --- | --- | --- | --- | --- |
| 1 | 100% | 1168 ms | 2842 ms | |
| 2 | 96.6% | 1055 ms | 1394 ms | model missed a transfer ("sent 3000 from Paytm to HDFC on 20 oct") |
| 3 | 100% | 1077 ms | 1324 ms | |
| 4 | 96.6% | 1064 ms | 1384 ms | model joined "uber 220 and lunch 180" into one transaction |
| 5 | 100% | 1123 ms | 1510 ms | |
| 6 | 93.1% | 1147 ms | 1357 ms | the same "uber ... lunch" miss, plus one Gemini 504 |
| 7 | 100% | 1109 ms | 2375 ms | |
| 8 | 100% | 1118 ms | 2309 ms | |
| 9 | 93.1% | 1138 ms | 1392 ms | two provider errors (429 and 504) |
| 10 | 96.6% | 1105 ms | 1415 ms | one provider 504 |

- The 6 new cases passed in all 10 runs (60 of 60).
- Every miss was on an older case: two model misreadings that are not about accounts (the
  "uber ... lunch" split twice, one missed transfer) and four Gemini provider errors (504 and
  429), which the eval counts as failures although they are not accuracy.
- The median of the run p50s is about 1.11 s, against the Phase 1 baseline of 1.26 s.
- **Same-day comparison (2026-11-01)**, the 23 cases both trees share, five runs each: before
  ticket 10, 1 misreading and 2 provider errors over 115 calls (p50 1093 ms); with ticket 10,
  2 misreadings and 0 errors (p50 1107 ms). The misses differ from run to run, which points to
  model noise rather than a regression, but a before-and-after on the same day is a small
  sample, not proof.

So the claim the spec asked for holds in this form: no latency regression, and accuracy at
Phase 1 level on the cases the change is about, with a small amount of model and provider
noise on the older cases. It does not hold as "100% on every run".

## Known limitations

### Product gaps

- **No account balances.** Accounts record where money moved, not how much each holds. Most
  transactions carry no account yet, so a balance would be wrong.
- **No cross-currency transfers.** A transfer's amount and both accounts must share one
  currency. There is no currency conversion.
- **The console email sender only.** No email provider is chosen. Outside production the reset
  email is printed in the API log; in production nothing is sent, so "Forgot password?" does
  not work for real users yet.
- **No two-factor sign-in**, and no email verification.
- **The offline parser can't tell an unknown account from a shop name.** "from Axis" with no
  Axis account stays a merchant. Only the model reading flags such a name, and then the reply
  says the account was not matched.
- **The model occasionally returns an empty transaction or a misspelt account name.** It leads
  to a clarification, not a wrong record.
- **No data export or account deletion**, and chat transcripts are still kept forever.
- Merchant rules cannot be made by hand, and there is no "never learn this merchant" switch.

### Quality and testing

- **Live eval noise.** Misses move from run to run (see the ticket 10 tables), so a single run
  cannot show a regression. The case set is 29 English cases, still without Hinglish or
  Gujarati.
- The same-day before-and-after comparison is small (five runs of 23 cases each).
- No browser end-to-end tests: the web app is covered by typecheck, lint and the production
  build only. The ticket 10 production build was run with webpack from a worktree that had no
  `node_modules`.
- Not tested: a rule whose category is archived is ignored in the code, but categories cannot
  be archived yet, so no test covers it.

### Follow-ups recorded in the tickets

- The 50-active-account limit is a count check with no database backstop, so two creates
  racing at 49 could both save (ticket 03). Lock the user's row or accept it.
- The merchant-rule list has its own copy of the transactions keyset cursor helper (ticket 05).
  Both should move into one shared helper.
- The Settings rule picker hard-codes the fallback slugs (`other`, `other_income`) that the
  backend also holds; the API stays the authority (ticket 05).

## Next steps

1. **Phase 2 code review** of the whole `phase-2/integration` branch, then fix what it finds.
   It runs after this ticket; it has not happened yet.
2. **Merge Phase 2 into `main`** after the review.
3. **Choose an email provider** so password reset works outside local development, and decide
   whether to add two-factor sign-in after it.
4. **Phase 3: split expenses with friends**, Splitwise-style. The brief is
   [`.scratch/phase-3/brief.md`](../.scratch/phase-3/brief.md); the next step is a grilling
   session on its open questions, then a spec and tickets.
5. Later phases keep the order in the [README roadmap](../README.md#roadmap). Account balances
   wait for imports (Phase 4) and debt tracking (Phase 7).
