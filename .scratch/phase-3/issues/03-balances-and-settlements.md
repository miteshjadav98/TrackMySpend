# 03: Balances and settlements

**What to build:** The Friends page shows each friend's balance per currency ("Jaymin owes you
₹500", "You owe Riya $10"). A user records a settlement with a friend in either direction
("Jaymin paid me 500", "I paid Jaymin 500"), optionally tagged with an account, and the
balance updates. A settlement never counts as spending or income. A friend's page lists their
shared expenses and settlements in date order.

Spec: `../spec.md` → User Stories 10, 30-35, 37, 48; Implementation Decisions → Model (settlement, balance).

**Blocked by:** 02

**Status:** done

- [x] Alembic revision for settlements on the single head.
- [x] Balances are computed in SQL, per currency, from shares and settlements as the spec defines; positive means the friend owes the user.
- [x] API: friends list includes balances; create, list and delete settlements; a friend's history (shared expenses and settlements). All scoped by user; others' rows are 404.
- [x] A settlement must be positive, between the user and one friend, in one currency; a settlement larger than the balance is allowed (it flips the balance) but the reply says so.
- [x] Only whoever recorded a settlement can delete it. Every write has its audit event in the same transaction.
- [x] Settlements never appear in summaries, category totals or the transaction list.
- [x] Integration test: mixed shared expenses (each side paying) and settlements in two currencies give hand-computed balances.
- [x] Web: balances on the Friends list, a friend detail page with history, and a "Record settlement" form (direction, amount, currency, date, optional account and note).
- [x] `npm run contracts` committed; API checks, full pytest, and web typecheck, lint and build pass.

## Comments

- Balances and a friend's history come from one SQL query (`friends/balances.py`) of signed lines, so they always agree. Zero balances are left out of the list.
- A settlement stores `paid_by_recorder` plus a `recorder_account_id` and a (so far unused) `friend_account_id`, ready for ticket 04.
- Archived friends take no new settlements (404), like new shared expenses.
- API: `GET /friends/{id}` (balances and history), `GET/POST /settlements`, `DELETE /settlements/{id}`. A settlement larger than the balance returns `exceedsBalance: true` and a `warning` sentence.
- Web: `/friends/[id]` page with the history and a "Record settlement" form; balances on the list rows.
- Merged into phase-3/integration as 068bded. API checks, web typecheck/lint/build pass; contracts have no drift; alembic head 0010 with no drift; full pytest 423 passed, 1 skipped (live LLM eval).
