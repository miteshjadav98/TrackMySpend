# 08: Docs and Phase 3 report

**What to build:** The docs describe the system as it now is, so a newcomer can understand and
explain friends, shared expenses, balances and settlements without reading the code first.

Spec: `../spec.md` (all sections).

**Blocked by:** 01, 02, 03, 04, 05, 06, 07

**Status:** ready-for-agent

- [x] README: new endpoints and how to try sharing locally with two users.
- [x] `docs/architecture.md`: the data model (friends, invites, shared expenses, shares, settlements, notices), the cross-user visibility rule (ADR 0001), the chat additions, and the "deliberately not doing yet" table (groups, percentage splits, currency conversion, push/email notices).
- [x] `GLOSSARY.md` matches the names used in the final code and UI.
- [x] `docs/phase-3-report.md`: what was built against the spec, tests run, live eval numbers, known limitations, next steps.
- [x] `docs/PROGRESS.md` updated.

## Comments

- README has the Phase 3 endpoints table, a "Split with friends" feature section and a two-user walk-through; `docs/architecture.md` gains a "Friends, shared expenses and settlements" section (ADR 0001 visibility rule, balances, notices, chat additions), the data-model rows and six "not doing yet" rows. GLOSSARY.md already matched the code and UI; only Invite and Notice were added. The report lists the known limitations as the code behaves, including the ones in the briefing. No code bug found; `understand_v4` latency and the no-idempotency-key settlement are recorded as limitations. `npm run check:api` passes.
