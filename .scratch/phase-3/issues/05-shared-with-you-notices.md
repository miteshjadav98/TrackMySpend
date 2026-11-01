# 05: "Shared with you" notices

**What to build:** A linked friend sees what changed since their last visit: a "Shared with you"
card on the home page and in chat ("Mitesh added Pizza: your share is ₹500", "Mitesh changed
Pizza: your share is now ₹600", "Mitesh deleted Pizza", "Jaymin recorded a settlement of
₹500", "Riya accepted your friend invite"), and a badge count in the nav. Notices are marked
read when seen.

Spec: `../spec.md` → User Stories 42, 46, 48; Implementation Decisions → Notices.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Alembic revision for notices on the single head.
- [ ] A notice is recorded, in the same database transaction as the change, for every other participant who is a user: shared expense added, changed (with the new share) or deleted; settlement recorded or deleted; invite accepted; and a pending invite for the invited user.
- [ ] API: list unread and recent notices, and mark them read; scoped by user.
- [ ] Web: the card on home and in chat, linking to the shared expense or friend; a nav badge with the unread count, loaded each time a page shows (React `<Activity>` re-runs effects; no one-shot guards).
- [ ] Integration test: Mitesh adds, edits and deletes a shared expense; Jaymin gets three notices in order; marking them read clears the count.
- [ ] `npm run contracts` committed; API checks, full pytest, and web typecheck, lint and build pass.

## Comments
