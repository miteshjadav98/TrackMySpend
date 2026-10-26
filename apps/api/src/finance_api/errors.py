"""One error envelope everywhere: {"error": {"code", "message", "requestId", "details"}}.

Validation errors never echo submitted values back (they could be passwords).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError
from starlette.exceptions import HTTPException as StarletteHTTPException

from finance_core.agents.chat import TurnFailedError
from finance_core.errors import (
    AuthenticationError,
    ConflictError,
    DomainError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
    ServiceUnavailableError,
    ValidationFailedError,
)
from finance_core.observability import request_id_var

logger = logging.getLogger(__name__)

_STATUS: tuple[tuple[type[DomainError], int], ...] = (
    (NotFoundError, 404),
    (ValidationFailedError, 422),
    (ConflictError, 409),
    (AuthenticationError, 401),
    (PermissionDeniedError, 403),
    (RateLimitedError, 429),
    (ServiceUnavailableError, 503),
    (TurnFailedError, 503),
)


def status_for(exc: DomainError) -> int:
    for cls, status in _STATUS:
        if isinstance(exc, cls):
            return status
    return 400


def error_response(
    status: int,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "error": {"code": code, "message": message, "requestId": request_id_var.get()}
    }
    if details:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_: Request, exc: DomainError) -> JSONResponse:
        headers = None
        if isinstance(exc, RateLimitedError):
            headers = {"Retry-After": str(exc.retry_after_seconds)}
        if isinstance(exc, AuthenticationError):
            headers = {"WWW-Authenticate": "Bearer"}
        return error_response(
            status_for(exc), exc.code, exc.message, details=exc.details or None, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ()) if part != "body"),
                "message": error.get("msg", "Invalid value"),
                "type": error.get("type"),
            }
            for error in exc.errors()
        ]
        return error_response(
            422, "validation_failed", "Some fields are invalid.", details={"fields": fields}
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return error_response(exc.status_code, code, str(exc.detail))

    # Database unreachable, failing over, pool exhausted or statement timeout: transient,
    # so 503 + Retry-After (clients and load balancers retry) rather than a generic 500.
    @app.exception_handler(OperationalError)
    @app.exception_handler(PoolTimeoutError)
    async def _database_unavailable(_: Request, exc: Exception) -> JSONResponse:
        logger.error("database unavailable", exc_info=exc)
        return error_response(
            503,
            "database_unavailable",
            "We can't reach your records right now. Please try again in a moment.",
            headers={"Retry-After": "5"},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", exc_info=exc)
        return error_response(500, "internal_error", "Something went wrong. Please try again.")
