"""Registration, login, and session lifecycle."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.auth.models import AuthSession
from finance_core.auth.passwords import hash_password, needs_rehash, verify_password
from finance_core.auth.schemas import AuthResult, ClientInfo, LoginRequest, Principal, RegisterRequest
from finance_core.clock import Clock
from finance_core.config import Settings
from finance_core.errors import AuthenticationError, ConflictError, ValidationFailedError
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

    def _check_password_policy(self, password: str) -> None:
        if len(password) < self._settings.password_min_length:
            raise ValidationFailedError(
                f"Password must be at least {self._settings.password_min_length} characters.",
                details={"field": "password"},
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
        self._check_password_policy(password)
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
