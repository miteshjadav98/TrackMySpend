# 04: Security settings: devices, sign out, change password

**What to build:** A user sees every device they are signed in on, signs out one of them or
all the others, and changes their password (which signs out every other device), through the
API and a new Settings → Security section.

Spec: `../spec.md` → Implementation Decisions → Account security (sessions and change
password; the password reset parts are ticket 07).

**Blocked by:** 01

**Status:** done

- [x] `GET /auth/sessions` lists the user's active sessions with device label, IP, createdAt, lastSeenAt and isCurrent; the current session comes first.
- [x] With two signed-in clients, one revokes the other via `DELETE /auth/sessions/{id}` and the revoked client gets 401 on its next request.
- [x] Revoking the current session signs this client out, like logout.
- [x] `POST /auth/sessions/revoke-others` leaves only the current session working and returns how many it revoked.
- [x] An unknown or another user's session id is 404.
- [x] `POST /auth/password`: a wrong current password is 422 on `currentPassword`; a too-short or unchanged new password is 422 on `newPassword`; on success other sessions get 401, the current one keeps working, the new password signs in and the old one doesn't.
- [x] Password changes are rate-limited like login.
- [x] Audit events: `auth.session_revoked`, `auth.other_sessions_revoked`, `auth.password_changed`.
- [x] Unit tests cover the device label reader (common browsers and operating systems, empty or unknown user agents).
- [x] Settings → Security shows the device list ("This device" marked, last active, sign out per device), "Sign out all other devices", and a change-password form (current, new, confirm) with clear errors.
- [x] Contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.

## Comments

Merged to `phase-2/integration` from branch `phase-2/t04-security` (head `a233a38`, which merges the integration tip into the work commit `a54f229`), in the commit "Merge ticket 04: security settings (devices, sign out, change password)". `a54f229` is labelled "WIP", but it is the complete ticket: the implementer finished the work in it and then merged the integration tip. Every criterion is met and checked against the code and tests (`tests/integration/test_account_security.py`, `tests/unit/test_device_label.py`). Checks on the merge: `npm run check:api` clean, `uv run pytest` 193 passed and 1 skipped (the live eval), one Alembic head (`0002`, no schema change) and `alembic check` reports no drift, `npm run check:web` and `npm run build:web` pass, `npm run contracts` gives no diff. At the merge, `PasswordChange` got its class docstring, and the contracts were regenerated for its new description.

Hand-off for ticket 07 (password reset): `AuthService.revoke_sessions(user_id, keep=None)` signs the user out of every working session and returns how many, but it does not commit. The reset confirm must call it, set the password and record its own audit event, then commit once so all three land together. `change_password` and `revoke_other_sessions` use it the same way.
