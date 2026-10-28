# 07: Forgot password with a reset link

**What to build:** From the login page a user asks for a reset link, gets it by email (printed
in the API log locally), opens it, sets a new password, and every session they had is signed
out. The reply to a request never reveals whether the email has an account.

Spec: `../spec.md` → Implementation Decisions → Account security (password reset tokens,
reset endpoints, reset link, email sender, web).

**Blocked by:** 04

**Status:** done

- [x] A new migration adds the password reset tokens table; `alembic check` reports no drift.
- [x] `POST /auth/password-reset` returns 202 with the same body for an existing user, an unknown email and a disabled user; a capturing email sender gets exactly one email for the existing active user and none otherwise.
- [x] The emailed link is `<WEB_BASE_URL>/reset-password#token=<token>`; only the token's SHA-256 is stored.
- [x] `POST /auth/password-reset/confirm` with a valid token returns 204, the new password signs in, the old one doesn't, and every earlier session gets 401.
- [x] A used token, an expired token (more than 30 minutes later on the test clock) and an unknown token are each 422 `reset_link_invalid`.
- [x] A new request makes the user's earlier unused link invalid.
- [x] Requests are rate-limited per email and per IP (429 beyond the limit).
- [x] The console sender logs the link outside production; in production it logs a warning without the link.
- [x] The email is sent outside the request path.
- [x] Audit events: `auth.password_reset_requested` (existing users only) and `auth.password_reset`.
- [x] `WEB_BASE_URL` and the new rate limits are settings, documented in `.env.example`.
- [x] Web: "Forgot password?" on the login page → forgot-password page (neutral confirmation) → reset-password page reading the token from the fragment (new password twice, clear invalid-link message with a way to request a new one) → login with a "password changed" notice. Both pages work signed out.
- [x] Contracts regenerated; API checks, the full pytest suite, and web typecheck, lint and build pass.

## Comments

Merged to `phase-2/integration` in the commit "Merge ticket 07: forgot password". All criteria met.
