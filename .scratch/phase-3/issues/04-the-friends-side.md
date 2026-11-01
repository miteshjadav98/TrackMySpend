# 04: The linked friend's side

**What to build:** When the user records a shared expense with a linked friend, it lands in the
friend's records straight away as their own expense for their share, filed under their merchant
rule, else the same built-in category the recorder used, else Other. The friend sees only the
shared expense (description, date, total, payer, shares), never anything else of the
recorder's. Edits and deletes by the recorder update the friend's share too. Settlements show
on both sides. When a friend links later, past shared expenses and settlements with them reach
them in one go.

Spec: `../spec.md` → User Stories 38-41, 43-44, 46-47, 49; Implementation Decisions → Model, Visibility.

**Blocked by:** 03

**Status:** done

- [x] Creating a shared expense with linked friends creates each linked friend's share transaction in the same database transaction, with an audit event for each affected user.
- [x] The friend's category follows the spec's order (their merchant rule; else their category with the recorder's built-in slug; else Other). Their share does not teach their merchant rule unless they change its category themselves.
- [x] The friend can change their own share's category, account and notes; amount, currency, date and type stay read-only for them; they cannot edit or delete the shared expense itself (403 or 404 as the codebase does for non-owners).
- [x] The friend's view of the shared expense names people as the friend calls them where known, else by the recorder's name for them, and never includes the recorder's account, category or notes.
- [x] Recorder edits and deletes update or remove every participant's share transaction together.
- [x] Balances and settlements agree on both sides; a settlement recorded by either side shows for both.
- [x] Accepting an invite brings over every existing shared expense and settlement between the two, creating the new friend's share transactions once (idempotent if retried).
- [x] Two- and three-user integration tests: Jaymin sees the pizza and his 500 counts in his summary; Riya, not in it, gets 404; Jaymin cannot see Mitesh's other transactions.
- [x] API checks, full pytest, and web typecheck, lint and build pass.

## Comments

Built in `friends/share_delivery.py` (a friend's share transaction, category order, idempotent
bring-over on accept), `shared_expenses.py` (delivery on create/edit/delete, participant read
with the friend's own names), `balances.py` and `settlements.py` (mirror lines so both sides
agree). `FriendService` now takes a clock. The seam for notices (ticket 05) is
`SharedExpenseService._audit_all` and the `affected` / `linked` user lists in create, update and
delete: the same users should get a notice. Not built: a way for the friend to tag their own
account on a settlement (`friend_account_id` is read but never set).

Merged into phase-3/integration (merge commit: see git log, subject "Merge ticket 04"). Full pytest: 507 passed, 1 skipped (live LLM eval). check:api, check:web, web build pass; contracts unchanged; alembic head 0010, no drift. All boxes ticked.
