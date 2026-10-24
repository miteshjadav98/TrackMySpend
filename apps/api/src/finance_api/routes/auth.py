from __future__ import annotations

import hashlib

from fastapi import APIRouter, Request, Response

from finance_api.deps import ClientInfoDep, ContainerDep, SessionDep
from finance_api.security import clear_session_cookie, session_token_from, set_session_cookie
from finance_core.auth.schemas import LoginRequest, RegisterRequest
from finance_core.auth.service import AuthService, normalize_email
from finance_core.users.schemas import MeView

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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
    result = await AuthService(session, settings, container.clock).register(body, client=client)
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
    settings = container.settings
    # Per-account limit stops a distributed guess against one account; per-IP limit stops
    # one client spraying many accounts.
    account = hashlib.sha256(normalize_email(str(body.email)).encode()).hexdigest()[:24]
    await container.rate_limiter.hit(
        "login-account", account, limit=settings.rate_limit_login_per_minute, window_seconds=60
    )
    await container.rate_limiter.hit(
        "login-ip",
        client.ip_address or "unknown",
        limit=settings.rate_limit_login_per_minute * 3,
        window_seconds=60,
    )
    result = await AuthService(session, settings, container.clock).login(body, client=client)
    set_session_cookie(response, result.token, result.expires_at, settings)
    return result.me


@router.post("/logout", status_code=204)
async def logout(
    request: Request, response: Response, session: SessionDep, container: ContainerDep
) -> None:
    token, _ = session_token_from(request, container.settings)
    if token:
        await AuthService(session, container.settings, container.clock).logout(token)
    clear_session_cookie(response, container.settings)
