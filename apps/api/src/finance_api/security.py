"""Session cookies and cross-site request protection."""

from __future__ import annotations

from datetime import datetime

from fastapi import Request, Response

from finance_core.config import Settings
from finance_core.errors import PermissionDeniedError

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def session_token_from(request: Request, settings: Settings) -> tuple[str | None, str]:
    """Token and how it was presented: browser cookie, or Bearer for API clients."""
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None, "bearer"
    return request.cookies.get(settings.session_cookie_name), "cookie"


def enforce_same_origin(request: Request, settings: Settings) -> None:
    """Defence in depth on top of SameSite=Lax cookies for state-changing requests."""
    if request.method in SAFE_METHODS:
        return
    origin = request.headers.get("origin")
    if origin is not None:
        if origin.rstrip("/") not in {o.rstrip("/") for o in settings.allowed_origins}:
            raise PermissionDeniedError("Request origin is not allowed.", code="origin_not_allowed")
        return
    fetch_site = request.headers.get("sec-fetch-site")
    if fetch_site is not None and fetch_site not in ("same-origin", "none"):
        raise PermissionDeniedError("Cross-site request blocked.", code="origin_not_allowed")


def set_session_cookie(
    response: Response, token: str, expires_at: datetime, settings: Settings
) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        expires=expires_at,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
        domain=settings.cookie_domain,
    )


def clear_session_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.session_cookie_name,
        path="/",
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def client_ip(request: Request) -> str | None:
    # Uvicorn applies X-Forwarded-For from trusted proxies (--forwarded-allow-ips), so
    # request.client is already the real client address behind the load balancer.
    return request.client.host if request.client else None
