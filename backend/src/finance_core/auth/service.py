"""Registration, login, and session lifecycle: listing and signing out a user's sessions."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.auth.devices import device_label
from finance_core.auth.models import AuthSession
from finance_core.auth.passwords import hash_password, needs_rehash, verify_password
from finance_core.auth.schemas import (
    AuthResult,
    ClientInfo,
    LoginRequest,
    PasswordChange,
    Principal,
    RegisterRequest,
    SessionView,
)
from finance_core.clock import Clock
from finance_core.config import Settings
from finance_core.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationFailedError,
)
from finance_core.users.models import FinancialProfile, User
from finance_core.users.schemas import MeView, ProfileView, UserView

# Sessions slide forward with activity but can never outlive this absolute cap.
_ABSOLUTE_SESSION_LIFETIME = timedelta(days=90)
# Avoid a write on every request: refresh last-seen/expiry at most this often.
_SESSION_TOUCH_INTERVAL = timedelta(hours=1)

INVALID_CREDENTIALS = "Incorrect email or password."


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_session_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings, clock: Clock) -> None:
        self._session = session
        self._settings = settings
        self._clock = clock

    def check_password_policy(self, password: str, *, field: str = "password") -> None:
        """The rules every new password follows, at registration, change and reset."""
        if len(password) < self._settings.password_min_length:
            raise ValidationFailedError(
                f"Password must be at least {self._settings.password_min_length} characters.",
                details={"field": field},
            )

    def _new_session(self, user_id: object, client: ClientInfo) -> tuple[AuthSession, str]:
        token = secrets.token_urlsafe(32)
        now = self._clock.now()
        record = AuthSession(
            user_id=user_id,
            token_hash=hash_session_token(token),
            last_seen_at=now,
            expires_at=now + timedelta(days=self._settings.session_ttl_days),
            user_agent=(client.user_agent or "")[:256] or None,
            ip_address=client.ip_address,
        )
        self._session.add(record)
        return record, token

    async def register(self, data: RegisterRequest, *, client: ClientInfo) -> AuthResult:
        password = data.password.get_secret_value()
        self.check_password_policy(password)
        email = normalize_email(str(data.email))

        existing = await self._session.scalar(select(User.id).where(User.email == email))
        if existing is not None:
            raise ConflictError("An account with this email already exists.", code="email_taken")

        user = User(
            email=email,
            password_hash=await hash_password(password),
            display_name=data.display_name,
            status="active",
        )
        self._session.add(user)
        await self._session.flush()
        profile = FinancialProfile(
            user_id=user.id,
            base_currency=data.base_currency,
            timezone=data.timezone,
            locale=data.locale,
        )
        self._session.add(profile)
        session_record, token = self._new_session(user.id, client)
        record_audit(
            self._session, user_id=user.id, actor="user", action="user.registered",
            entity_type="user", entity_id=user.id,
        )  # fmt: skip
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            raise ConflictError(
                "An account with this email already exists.", code="email_taken"
            ) from None
        me = MeView(user=UserView.model_validate(user), profile=ProfileView.model_validate(profile))
        return AuthResult(me=me, token=token, expires_at=session_record.expires_at)

    async def login(self, data: LoginRequest, *, client: ClientInfo) -> AuthResult:
        email = normalize_email(str(data.email))
        password = data.password.get_secret_value()
        user = await self._session.scalar(select(User).where(User.email == email))
        valid = await verify_password(user.password_hash if user else None, password)
        if user is None or not valid:
            if user is not None:
                record_audit(
                    self._session, user_id=user.id, actor="user", action="auth.login_failed",
                    entity_type="user", entity_id=user.id,
                )  # fmt: skip
                await self._session.commit()
            raise AuthenticationError(INVALID_CREDENTIALS, code="invalid_credentials")
        if user.status != "active":
            raise AuthenticationError("This account is disabled.", code="account_disabled")

        assert user.password_hash is not None
        if needs_rehash(user.password_hash):
            user.password_hash = await hash_password(password)
        profile = await self._session.get(FinancialProfile, user.id)
        assert profile is not None
        session_record, token = self._new_session(user.id, client)
        record_audit(
            self._session, user_id=user.id, actor="user", action="auth.login",
            entity_type="user", entity_id=user.id,
        )  # fmt: skip
        await self._session.commit()
        me = MeView(user=UserView.model_validate(user), profile=ProfileView.model_validate(profile))
        return AuthResult(me=me, token=token, expires_at=session_record.expires_at)

    async def authenticate(self, token: str) -> Principal | None:
        """Resolve a session token to a principal, sliding its expiry with activity."""
        if not token or len(token) > 256:
            return None
        now = self._clock.now()
        row = (
            await self._session.execute(
                select(AuthSession)
                .join(User, User.id == AuthSession.user_id)
                .where(
                    AuthSession.token_hash == hash_session_token(token),
                    AuthSession.revoked_at.is_(None),
                    AuthSession.expires_at > now,
                    User.status == "active",
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        if now - row.last_seen_at >= _SESSION_TOUCH_INTERVAL:
            row.last_seen_at = now
            row.expires_at = min(
                now + timedelta(days=self._settings.session_ttl_days),
                row.created_at + _ABSOLUTE_SESSION_LIFETIME,
            )
            await self._session.commit()
        return Principal(user_id=row.user_id, session_id=row.id)

    async def logout(self, token: str) -> None:
        await self._session.execute(
            update(AuthSession)
            .where(
                AuthSession.token_hash == hash_session_token(token),
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=self._clock.now())
        )
        await self._session.commit()

    async def session_expiry(self, principal: Principal) -> datetime | None:
        return await self._session.scalar(
            select(AuthSession.expires_at).where(AuthSession.id == principal.session_id)
        )

    # --- Account security: the user's own sessions and password ---------------------------

    def _working_sessions_of(self, user_id: uuid.UUID) -> tuple[ColumnElement[bool], ...]:
        """The user's sessions that still sign them in: not signed out and not expired."""
        return (
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > self._clock.now(),
        )

    async def list_sessions(self, principal: Principal) -> list[SessionView]:
        """Every device the user is signed in on: this one first, then the most recently active."""
        is_this_device = AuthSession.id == principal.session_id
        rows = await self._session.scalars(
            select(AuthSession)
            .where(*self._working_sessions_of(principal.user_id))
            .order_by(is_this_device.desc(), AuthSession.last_seen_at.desc(), AuthSession.id)
        )
        return [
            SessionView(
                id=row.id,
                device=device_label(row.user_agent),
                ip_address=row.ip_address,
                created_at=row.created_at,
                last_seen_at=row.last_seen_at,
                is_current=row.id == principal.session_id,
            )
            for row in rows
        ]

    async def revoke_session(
        self, principal: Principal, session_id: uuid.UUID, *, request_id: str | None = None
    ) -> None:
        """Sign out one of the user's devices, which may be this one.

        The statement matches the session id *and* the caller's user id, so another user's
        session is "not found", exactly like an id that never existed.
        """
        revoked_id = await self._session.scalar(
            update(AuthSession)
            .where(AuthSession.id == session_id, *self._working_sessions_of(principal.user_id))
            .values(revoked_at=self._clock.now())
            .returning(AuthSession.id)
        )
        if revoked_id is None:
            raise NotFoundError("That session was not found. It may already be signed out.")
        record_audit(
            self._session, user_id=principal.user_id, actor="user", action="auth.session_revoked",
            entity_type="session", entity_id=session_id,
            data={"thisDevice": session_id == principal.session_id}, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()

    async def revoke_other_sessions(
        self, principal: Principal, *, request_id: str | None = None
    ) -> int:
        """Sign out every device except this one; returns how many were signed out."""
        revoked = await self.revoke_sessions(principal.user_id, keep=principal.session_id)
        record_audit(
            self._session, user_id=principal.user_id, actor="user",
            action="auth.other_sessions_revoked", entity_type="user",
            entity_id=principal.user_id, data={"revoked": revoked}, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        return revoked

    async def revoke_sessions(self, user_id: uuid.UUID, *, keep: uuid.UUID | None = None) -> int:
        """Sign out every working session of the user except `keep`; returns how many.

        Pass `keep=None` to sign the user out everywhere. This does not commit: the caller
        commits it together with the change that caused it and that change's audit event.
        """
        statement = update(AuthSession).where(*self._working_sessions_of(user_id))
        if keep is not None:
            statement = statement.where(AuthSession.id != keep)
        revoked_ids = await self._session.scalars(
            statement.values(revoked_at=self._clock.now()).returning(AuthSession.id)
        )
        return len(revoked_ids.all())

    async def change_password(
        self, principal: Principal, data: PasswordChange, *, request_id: str | None = None
    ) -> None:
        """Replace the user's password, proving it is them by the current one."""
        current = data.current_password.get_secret_value()
        new = data.new_password.get_secret_value()
        user = await self._session.get(User, principal.user_id)
        assert user is not None  # the principal was just authenticated as an active user

        # 1. The current password: a borrowed, unlocked device must not take the account over.
        if not await verify_password(user.password_hash, current):
            raise ValidationFailedError(
                "Your current password is incorrect.", details={"field": "currentPassword"}
            )
        # 2. The new password follows the same rules as at registration, and must differ.
        self.check_password_policy(new, field="newPassword")
        if new == current:
            raise ValidationFailedError(
                "Choose a new password that is different from your current one.",
                details={"field": "newPassword"},
            )

        user.password_hash = await hash_password(new)
        # Whoever knew the old password may be signed in elsewhere: sign out every other
        # device. This one stays signed in, since it just proved the current password.
        revoked = await self.revoke_sessions(user.id, keep=principal.session_id)
        record_audit(
            self._session, user_id=user.id, actor="user", action="auth.password_changed",
            entity_type="user", entity_id=user.id, data={"otherSessionsRevoked": revoked},
            request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
