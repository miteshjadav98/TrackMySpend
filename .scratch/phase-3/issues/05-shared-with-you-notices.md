# 05: "Shared with you" notices

**What to build:** A linked friend sees what changed since their last visit: a "Shared with you"
card on the home page and in chat ("Mitesh added Pizza: your share is ₹500", "Mitesh changed
Pizza: your share is now ₹600", "Mitesh deleted Pizza", "Jaymin recorded a settlement of
₹500", "Riya accepted your friend invite"), and a badge count in the nav. Notices are marked
read when seen.

Spec: `../spec.md` → User Stories 42, 46, 48; Implementation Decisions → Notices.

**Blocked by:** 04

**Status:** done

- [x] Alembic revision for notices on the single head.
- [x] A notice is recorded, in the same database transaction as the change, for every other participant who is a user: shared expense added, changed (with the new share) or deleted; settlement recorded or deleted; invite accepted; and a pending invite for the invited user.
- [x] API: list unread and recent notices, and mark them read; scoped by user.
- [x] Web: the card on home and in chat, linking to the shared expense or friend; a nav badge with the unread count, loaded each time a page shows (React `<Activity>` re-runs effects; no one-shot guards).
- [x] Integration test: Mitesh adds, edits and deletes a shared expense; Jaymin gets three notices in order; marking them read clears the count.
- [x] `npm run contracts` committed; API checks, full pytest, and web typecheck, lint and build pass.

## Comments

Built in `friends/notices.py` (`NoticeWriter` adds the row in the caller's session; `NoticeService`
lists and marks read), migration `0011`, routes `GET /api/v1/notices` and `POST /api/v1/notices/read`.
Hooks sit next to the audit calls in `SharedExpenseService` (create, update, delete), `SettlementService`
(create, delete) and `FriendService` (invite sent, accept). Anything that records a settlement through
`SettlementService.create` gets a notice with no extra work.

Decisions: the message is worded at read time from stored facts, so the amount follows the reader's
locale. A friend taken out of a split is told the expense was deleted. An invitee with no account yet
gets no notice (they see the invite in their list when they sign up). There is no separate home page
(`/chat` is home), so the card is at the top of the chat view and of the Friends page; it marks notices
read as they appear but keeps them on screen for that visit. The badge sits on the Friends nav item and
re-asks on every page change.

Full pytest: 517 passed, 1 skipped (live LLM eval). check:api, check:web, web build pass; contracts
regenerated; alembic head 0011, no drift.

Merged into phase-3/integration. Merge checks: full pytest 517 passed, 1 skipped (live LLM eval); check:api, check:web, web build pass; contracts no real diff; alembic head 0011, no drift. All boxes ticked.
