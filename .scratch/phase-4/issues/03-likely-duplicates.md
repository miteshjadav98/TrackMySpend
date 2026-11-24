# 03: Likely duplicates

**What to build:** When a statement row matches a transaction the user already has in that
account (same date, amount and direction), for example a lunch typed in chat, the preview marks
it "likely duplicate", unticks it, and shows what it matches. The user can tick it back on.

Spec: `../spec.md` → User Stories 23-25; Implementation Decisions → Likely duplicates and transfers.

**Blocked by:** 01

**Status:** done

- [x] Matching runs in SQL against the user's live transactions in that account (same date, amount, direction), excluding rows from an earlier import of the same rows (those are skipped, not flagged).
- [x] Each existing transaction matches at most one statement row, so two identical payments with one hand-typed entry leave one row ticked.
- [x] The preview shows the matched transaction (description, source) and the likely-duplicate count; ticking it back on imports it.
- [x] Integration tests: a chat-entered lunch is flagged; two identical rows with one hand-typed entry flag only one; ticked-back duplicates import.
- [x] API checks, full pytest, and web typecheck, lint and build pass.

## Comments

Merged as `5bfcebe`. The combined backend suite passed 724 tests with one opt-in
test skipped. API checks, schema drift, web typecheck, lint and the webpack build passed.
