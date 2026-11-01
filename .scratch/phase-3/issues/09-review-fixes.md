# 09: Code review fixes

**What to build:** Fix the findings of the Phase 3 code review of `phase-3/integration`, so
linking needs proof of the email, a friend who owes money is never lost, a chat message saves all
or nothing, and settlements are never doubled.

Spec: `../spec.md`. Owner decision (2026-11-01): accepting an invite requires a one-time code
sent to the invited email.

**Blocked by:** 01-08

**Status:** done

- [x] Accepting an invite first sends a 6-digit one-time code to the invited email through the existing email sender (printed in the API log locally, like password reset); the link (and bring-over) happens only after the right code is entered. Codes are stored hashed, expire (15 minutes), are single-use, and attempts are rate-limited; a wrong or expired code changes nothing.
- [x] Web: the accept button asks for the code ("We sent a code to <email>"), with resend.
- [x] Removing a friend with a non-zero balance in any currency is refused with a clear 409 ("settle up first"); nothing is archived. Archived friends can be unarchived from the Friends page (API + web).
- [x] A chat message mixing shared and ordinary expenses saves everything in one database transaction: if any part fails, nothing from that message is saved.
- [x] Creating a settlement through the API accepts an `Idempotency-Key` header like transactions do; a retried request returns the first settlement instead of a second one.
- [x] A linked friend can tag their own account on a settlement (story 35): sets `friend_account_id`, shown only on their side.
- [x] Chat balance and settlement replies tell two friends with the same name apart by email (story 11).
- [x] Regression tests named as sentences for each.

## Comments

Implementer (t09): one migration, 0012, adds `friend_invites.code_hash`, `code_expires_at`,
`code_wrong_tries` and `settlements.idempotency_key` (unique per recorder).
- Invite code: `POST /friend-invites/{id}/code` emails the code (rate limit 5 per user per hour,
  setting `rate_limit_invite_code_per_hour`); `POST .../accept` now needs `{code}`. Five wrong
  tries burn a code; a newer code replaces the older one. The wrong-try count is the only thing a
  wrong code changes.
- Removing a friend with any balance is a 409 `friend_has_balance`; `GET /friends?archived=true`
  and `POST /friends/{id}/unarchive` bring them back (Friends page: collapsed "Removed friends").
- `create_resolved` and `SharedExpenseService.create` take `commit=False`; the chat save adds
  friends and categories first (those commit), then writes everything and commits once. Friends
  added for a message that then fails stay added (a retry finds them by name).
- `POST /settlements` takes `Idempotency-Key` (201 first time, 200 on replay; a replay carries no
  new warning). `PATCH /settlements/{id}` with `accountId` sets the friend's own tag; the
  recorder gets a 404 there (they tag at create time).
- Chat replies name same-named friends as "Name (email)" in balance answers and in the "which
  one" questions.
- Test helper `accept_invite` in `tests/conftest.py` does the two-step accept for older tests.


Merged into phase-3/integration as 39d6e7a. Merge checks: 609 passed, 1 skipped (live LLM eval); check:api, check:web, web build, contracts (no diff), alembic heads (0012) and alembic check all clean.
