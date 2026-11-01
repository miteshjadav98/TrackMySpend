# 03: Balances and settlements

**What to build:** The Friends page shows each friend's balance per currency ("Jaymin owes you
₹500", "You owe Riya $10"). A user records a settlement with a friend in either direction
("Jaymin paid me 500", "I paid Jaymin 500"), optionally tagged with an account, and the
balance updates. A settlement never counts as spending or income. A friend's page lists their
shared expenses and settlements in date order.

Spec: `../spec.md` → User Stories 10, 30-35, 37, 48; Implementation Decisions → Model (settlement, balance).

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Alembic revision for settlements on the single head.
- [ ] Balances are computed in SQL, per currency, from shares and settlements as the spec defines; positive means the friend owes the user.
- [ ] API: friends list includes balances; create, list and delete settlements; a friend's history (shared expenses and settlements). All scoped by user; others' rows are 404.
- [ ] A settlement must be positive, between the user and one friend, in one currency; a settlement larger than the balance is allowed (it flips the balance) but the reply says so.
- [ ] Only whoever recorded a settlement can delete it. Every write has its audit event in the same transaction.
- [ ] Settlements never appear in summaries, category totals or the transaction list.
- [ ] Integration test: mixed shared expenses (each side paying) and settlements in two currencies give hand-computed balances.
- [ ] Web: balances on the Friends list, a friend detail page with history, and a "Record settlement" form (direction, amount, currency, date, optional account and note).
- [ ] `npm run contracts` committed; API checks, full pytest, and web typecheck, lint and build pass.

## Comments
