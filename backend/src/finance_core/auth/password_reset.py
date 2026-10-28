"""Password reset: replacing a forgotten password through a single-use, short-lived link.

The security properties, and where each one is enforced:

- No account enumeration: the API replies the same whatever the email, and the reply does
  not wait for `request_reset`, so its timing gives nothing away (see `routes/auth.py`).
- The token is never stored: only its SHA-256, like a session token.
- A link expires after 30 minutes, works once, and a newer link replaces it.
- Using a link signs the user out everywhere, so whoever knew the old password loses access.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.auth.models import PasswordResetToken
from finance_core.auth.passwords import hash_password
from finance_core.auth.schemas import PasswordResetConfirm
from finance_core.auth.service import AuthService, normalize_email
from finance_core.clock import Clock
from finance_core.config import Settings
from finance_core.email_sender import EmailMessage
from finance_core.errors import ValidationFailedError
from finance_core.users.models import User

RESET_LINK_LIFETIME = timedelta(minutes=30)


def hash_reset_token(token: str) -> bytes:
    """The SHA-256 stored in place of the token. A fast hash is enough: the token is 256 random
    bits, so unlike a password it cannot be guessed from its hash."""
    return hashlib.sha256(token.encode("utf-8")).digest()


class PasswordResetService:
    """Creates reset links for forgotten passwords and redeems them."""

    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock

    async def request_reset(
        self, email: str, *, ip_address: str | None, request_id: str | None = None
    ) -> EmailMessage | None:
        """Create a reset link for the account with this email and return the email to send.

        Returns None when there is no active account with this email; a disabled account
        cannot sign in, so it gets no link either. The caller must not tell the requester.
        """
        user = await self._session.scalar(
            select(User).where(User.email == normalize_email(email), User.status == "active")
        )
        if user is None:
            return None

        now = self._clock.now()
        # Only the newest link works: the user's earlier unused links expire now.
        await self._session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
            .values(expires_at=now)
        )
        token = secrets.token_urlsafe(32)  # 256 random bits
        self._session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_reset_token(token),
                expires_at=now + RESET_LINK_LIFETIME,
                requested_from_ip=ip_address,
            )
        )
        record_audit(
            self._session, user_id=user.id, actor="user", action="auth.password_reset_requested",
            entity_type="user", entity_id=user.id, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        return self._reset_email(user.email, token)

    async def reset_password(
        self, data: PasswordResetConfirm, *, request_id: str | None = None
    ) -> None:
        """Set a new password with the token from a reset link, and sign out every session.

        The new password, the used link and the signed-out sessions commit together.
        """
        auth = AuthService(self._session, self._settings, self._clock)
        new_password = data.new_password.get_secret_value()

        # 1. The new password follows the same rules as at registration. This is checked
        #    first, so a password the user must retype does not use up their link.
        auth.check_password_policy(new_password, field="newPassword")

        # 2. The link must be one we sent, unused, unexpired, and for an active account.
        user_id = await self._use_link(data.token.get_secret_value())
        if user_id is None:
            # One answer for unknown, used and expired links: the fix is the same for all three.
            raise ValidationFailedError(
                "This reset link is invalid or has expired. Request a new one.",
                code="reset_link_invalid",
            )

        user = await self._session.get(User, user_id)
        assert user is not None  # the link was just matched to an active user
        user.password_hash = await hash_password(new_password)
        # 3. Whoever knew the old password may be signed in somewhere: sign out every session.
        revoked = await auth.revoke_sessions(user_id)
        record_audit(
            self._session, user_id=user_id, actor="user", action="auth.password_reset",
            entity_type="user", entity_id=user_id, data={"sessionsRevoked": revoked},
            request_id=request_id,
        )  # fmt: skip
        await self._session.commit()

    async def _use_link(self, token: str) -> uuid.UUID | None:
        """Mark the link used and return its user, if the link can still be used.

        A single UPDATE both checks and claims the link, so two requests with the same link
        cannot both succeed: the second waits for the first, then finds the link used.
        """
        now = self._clock.now()
        return await self._session.scalar(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.token_hash == hash_reset_token(token),
                PasswordResetToken.used_at.is_(None),  # it works once
                PasswordResetToken.expires_at > now,  # and only for 30 minutes
                PasswordResetToken.user_id == User.id,
                User.status == "active",  # a disabled account stays locked
            )
            .values(used_at=now)
            .returning(PasswordResetToken.user_id)
        )

    def _reset_email(self, address: str, token: str) -> EmailMessage:
        # The token travels in the URL fragment, which browsers never send to a server, so
        # it stays out of server logs and Referer headers.
        link = f"{self._settings.web_base_url.rstrip('/')}/reset-password#token={token}"
        return EmailMessage(
            to=address,
            subject="Reset your MoneyMoney password",
            text=(
                "Someone asked to reset the password for your MoneyMoney account.\n\n"
                f"To choose a new password, open this link within 30 minutes:\n{link}\n\n"
                "The link works once. Using it signs you out on every device.\n"
                "If you didn't ask for this, ignore this email: your password stays the same."
            ),
        )
