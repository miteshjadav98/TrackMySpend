# 04: Security settings: devices, sign out, change password

**What to build:** A user sees every device they are signed in on, signs out one of them or
all the others, and changes their password (which signs out every other device), through the
API and a new Settings → Security section.

Spec: `../spec.md` → Implementation Decisions → Account security (sessions and change
password; the password reset parts are ticket 07).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `GET /auth/sessions` lists the user's active sessions with device label, IP, createdAt, lastSeenAt and isCurrent; the current session comes first.
- [ ] With two signed-in clients, one revokes the other via `DELETE /auth/sessions/{id}` and the revoked client gets 401 on its next request.
- [ ] Revoking the current session signs this client out, like logout.
- [ ] `POST /auth/sessions/revoke-others` leaves only the current session working and returns how many it revoked.
- [ ] An unknown or another user's session id is 404.
- [ ] `POST /auth/password`: a wrong current password is 422 on `currentPassword`; a too-short or unchanged new password is 422 on `newPassword`; on success other sessions get 401, the current one keeps working, the new password signs in and the old one doesn't.
- [ ] Password changes are rate-limited like login.
- [ ] Audit events: `auth.session_revoked`, `auth.other_sessions_revoked`, `auth.password_changed`.
- [ ] Unit tests cover the device label reader (common browsers and operating systems, empty or unknown user agents).
- [ ] Settings → Security shows the device list ("This device" marked, last active, sign out per device), "Sign out all other devices", and a change-password form (current, new, confirm) with clear errors.
- [ ] Contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.
