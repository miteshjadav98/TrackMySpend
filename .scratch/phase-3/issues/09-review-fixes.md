# 09: Code review fixes

**What to build:** Fix the findings of the Phase 3 code review of `phase-3/integration`, so
linking needs proof of the email, a friend who owes money is never lost, a chat message saves all
or nothing, and settlements are never doubled.

Spec: `../spec.md`. Owner decision (2026-11-01): accepting an invite requires a one-time code
sent to the invited email.

**Blocked by:** 01-08

**Status:** in progress

- [ ] Accepting an invite first sends a 6-digit one-time code to the invited email through the existing email sender (printed in the API log locally, like password reset); the link (and bring-over) happens only after the right code is entered. Codes are stored hashed, expire (15 minutes), are single-use, and attempts are rate-limited; a wrong or expired code changes nothing.
- [ ] Web: the accept button asks for the code ("We sent a code to <email>"), with resend.
- [ ] Removing a friend with a non-zero balance in any currency is refused with a clear 409 ("settle up first"); nothing is archived. Archived friends can be unarchived from the Friends page (API + web).
- [ ] A chat message mixing shared and ordinary expenses saves everything in one database transaction: if any part fails, nothing from that message is saved.
- [ ] Creating a settlement through the API accepts an `Idempotency-Key` header like transactions do; a retried request returns the first settlement instead of a second one.
- [ ] A linked friend can tag their own account on a settlement (story 35): sets `friend_account_id`, shown only on their side.
- [ ] Chat balance and settlement replies tell two friends with the same name apart by email (story 11).
- [ ] Regression tests named as sentences for each.

## Comments
