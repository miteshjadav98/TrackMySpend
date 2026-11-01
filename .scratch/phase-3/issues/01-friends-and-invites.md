# 01: Friends list and invites

**What to build:** A user keeps a friends list on a new Friends page: add a friend by name with
an optional email, rename them, set or change the email, and remove them. A friend whose email
belongs to a MoneyMoney user gets an in-app invite; accepting links the two users both ways, so
each appears in the other's list. An invite to an email with no user waits until someone signs
up with it.

Spec: `../spec.md` → User Stories 1-11, Implementation Decisions → Model (friend rows, linking).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A new `friends` domain module (joins the import-linter domain contract) with an Alembic revision on the single head for friends and friend invites; `uv run alembic check` reports no drift.
- [ ] API: list friends, add, rename, set email, remove; list incoming invites, accept, decline. Every query is scoped by the authenticated user; another user's friend or invite is a 404.
- [ ] Adding a friend with an email that belongs to a user creates a pending invite for that user; an email with no user creates an invite that the user who later signs up with that email sees.
- [ ] Accepting links both ways: the invited user gets a friend row for the inviter (or an existing unlinked row with the inviter's email is linked), and the inviter's row is linked. Declining leaves the inviter's friend unlinked.
- [ ] A user cannot add themselves; the same email cannot be added twice; names are trimmed and limited in length.
- [ ] Removing a friend deletes them for now (ticket 02 changes this to archive once shared expenses exist; leave a clear seam for it).
- [ ] Every write records its audit event in the same database transaction.
- [ ] Web: a Friends page in the nav with the list, an add-friend form, rename and remove, and an incoming-invites section with accept and decline. Works in dark mode and survives client-side navigation (React `<Activity>`).
- [ ] Two-user integration tests: Mitesh invites Jaymin, Jaymin accepts, both lists show each other; a third user gets 404s.
- [ ] `npm run contracts` committed; API checks, full pytest, and web typecheck, lint and build pass.

## Comments
