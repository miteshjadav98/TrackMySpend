"""Sign-up, sign-in and sign-out, plus account security: the user's signed-in sessions."""

from __future__ import annotations

import hashlib
import uuid

from fastapi import APIRouter, Request, Response

from finance_api.deps import ClientInfoDep, ContainerDep, PrincipalDep, RequestIdDep, SessionDep
from finance_api.security import clear_session_cookie, session_token_from, set_session_cookie
from finance_core.auth.schemas import (
    ClientInfo,
    LoginRequest,
    PasswordChange,
    RegisterRequest,
    RevokedSessionsView,
    SessionView,
)
from finance_core.auth.service import AuthService, normalize_email
from finance_core.users.schemas import MeView

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _auth(session: SessionDep, container: ContainerDep) -> AuthService:
    return AuthService(session, container.settings, container.clock)


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
    account = hashlib.sha256(normalize_email(str(body.email)).encode()).hexdigest()[:24]
    await _limit_password_guesses(container, scope="login", account=account, client=client)
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
