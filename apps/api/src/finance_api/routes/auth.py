"""Sign-up, sign-in and sign-out, password reset, and account security: the user's sessions."""

from __future__ import annotations

import hashlib
import logging
import uuid

from fastapi import APIRouter, Request, Response

from finance_api.container import AppContainer
from finance_api.deps import ClientInfoDep, ContainerDep, PrincipalDep, RequestIdDep, SessionDep
from finance_api.security import clear_session_cookie, session_token_from, set_session_cookie
from finance_core.auth.password_reset import PasswordResetService
from finance_core.auth.schemas import (
    ClientInfo,
    LoginRequest,
    PasswordChange,
    PasswordResetConfirm,
    PasswordResetRequest,
    PasswordResetRequested,
    RegisterRequest,
    RevokedSessionsView,
    SessionView,
)
from finance_core.auth.service import AuthService, normalize_email
from finance_core.users.schemas import MeView

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _auth(session: SessionDep, container: ContainerDep) -> AuthService:
    return AuthService(session, container.settings, container.clock)


def _email_key(email: str) -> str:
    """A rate-limit key for an email address that does not put the address itself in Redis."""
    return hashlib.sha256(normalize_email(email).encode()).hexdigest()[:24]


async def _limit_password_guesses(
    container: ContainerDep, *, scope: str, account: str, client: ClientInfo
) -> None:
    """Every request that checks a password counts against two limits, per minute.

    The per-account limit stops a distributed guess against one account; the per-IP limit
    stops one client spraying many accounts.
    """
    settings = container.settings
    await container.rate_limiter.hit(
        f"{scope}-account", account, limit=settings.rate_limit_login_per_minute, window_seconds=60
    )
    await container.rate_limiter.hit(
        f"{scope}-ip",
        client.ip_address or "unknown",
        limit=settings.rate_limit_login_per_minute * 3,
        window_seconds=60,
    )


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest,
    response: Response,
    session: SessionDep,
    container: ContainerDep,
    client: ClientInfoDep,
) -> MeView:
    settings = container.settings
    await container.rate_limiter.hit(
        "register-ip",
        client.ip_address or "unknown",
        limit=settings.rate_limit_register_per_hour,
        window_seconds=3600,
    )
    result = await _auth(session, container).register(body, client=client)
    set_session_cookie(response, result.token, result.expires_at, settings)
    return result.me


@router.post("/login")
async def login(
    body: LoginRequest,
    response: Response,
    session: SessionDep,
    container: ContainerDep,
    client: ClientInfoDep,
) -> MeView:
    await _limit_password_guesses(
        container, scope="login", account=_email_key(str(body.email)), client=client
    )
    result = await _auth(session, container).login(body, client=client)
    set_session_cookie(response, result.token, result.expires_at, container.settings)
    return result.me


@router.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: SessionDep, container: ContainerDep
) -> None:
    token, _ = session_token_from(request, container.settings)
    if token:
        await _auth(session, container).logout(token)
    clear_session_cookie(response, container.settings)


# --- Password reset: for a signed-out user who forgot their password ------------------------

RESET_REQUESTED = PasswordResetRequested(
    message="If an account exists for that email, we've sent it a link to reset the password."
)


@router.post("/password-reset", status_code=202)
async def request_password_reset(
    body: PasswordResetRequest,
    container: ContainerDep,
    client: ClientInfoDep,
    request_id: RequestIdDep,
) -> PasswordResetRequested:
    """Email a reset link to the account with this email, if there is one.

    The reply never says whether the account exists: it is always the same body, and it
    does not wait for the account lookup or the email, so its timing gives nothing away.
    """
    # Every request sends an email or could, so limit it per address (whether or not it
    # has an account, which keeps the limit from revealing that) and per client IP.
    settings = container.settings
    await container.rate_limiter.hit(
        "password-reset-email",
        _email_key(str(body.email)),
        limit=settings.rate_limit_password_reset_per_email_per_hour,
        window_seconds=3600,
    )
    await container.rate_limiter.hit(
        "password-reset-ip",
        client.ip_address or "unknown",
        limit=settings.rate_limit_password_reset_per_ip_per_hour,
        window_seconds=3600,
    )
    container.spawn(
        _email_reset_link(
            container, str(body.email), ip_address=client.ip_address, request_id=request_id
        )
    )
    return RESET_REQUESTED


async def _email_reset_link(
    container: AppContainer, email: str, *, ip_address: str | None, request_id: str | None
) -> None:
    """Runs after the reply has gone: create the link if the account exists, then email it."""
    try:
        async with container.session_factory() as session:
            message = await PasswordResetService(
                session, container.settings, container.clock
            ).request_reset(email, ip_address=ip_address, request_id=request_id)
        if message is not None:
            await container.email_sender.send(message)
    except Exception:
        # Nobody is waiting on this any more, so the log is the only place a failure shows.
        logger.exception("password reset link could not be created or sent")


@router.post("/password-reset/confirm", status_code=204)
async def reset_password(
    body: PasswordResetConfirm,
    response: Response,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> None:
    """Set a new password with the token from an emailed reset link.

    Every session of the user is signed out, so this browser drops any cookie it still has.
    No rate limit is needed here: a token is 256 random bits, so it cannot be guessed.
    """
    await PasswordResetService(session, container.settings, container.clock).reset_password(
        body, request_id=request_id
    )
    clear_session_cookie(response, container.settings)


# --- Account security: the caller's own sessions -------------------------------------------
# Every endpoint below needs a signed-in caller (PrincipalDep) and acts only on that user's
# sessions; cookie-authenticated writes also pass the same-origin check in PrincipalDep.


@router.get("/sessions")
async def list_sessions(
    principal: PrincipalDep, session: SessionDep, container: ContainerDep
) -> list[SessionView]:
    """The caller's signed-in sessions, this one first."""
    return await _auth(session, container).list_sessions(principal)


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: uuid.UUID,
    response: Response,
    principal: PrincipalDep,
    session: SessionDep,
    container: ContainerDep,
    request_id: RequestIdDep,
) -> None:
    """Sign out one of the caller's devices. Another user's session id is a 404."""
    await _auth(session, container).revoke_session(principal, session_id, request_id=request_id)
    # Signing out this device is the same as logging out, so the browser drops its cookie too.
    if session_id == principal.session_id:
        clear_session_cookie(response, container.settings)


@router.post("/sessions/revoke-others")
async def revoke_other_sessions(
    principal: PrincipalDep, session: SessionDep, container: ContainerDep, request_id: RequestIdDep
) -> RevokedSessionsView:
    """Sign out every device except the one making this request."""
    revoked = await _auth(session, container).revoke_other_sessions(
        principal, request_id=request_id
    )
    return RevokedSessionsView(revoked=revoked)


@router.post("/password", status_code=204)
async def change_password(
    body: PasswordChange,
    principal: PrincipalDep,
    session: SessionDep,
    container: ContainerDep,
    client: ClientInfoDep,
    request_id: RequestIdDep,
) -> None:
    """Change the caller's password; every other device is signed out, this one stays in.

    It checks the current password, so it is rate-limited like login: a stolen session must
    not become a way to guess the password.
    """
    await _limit_password_guesses(
        container, scope="password-change", account=str(principal.user_id), client=client
    )
    await _auth(session, container).change_password(principal, body, request_id=request_id)
