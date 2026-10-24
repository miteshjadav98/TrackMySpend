"""Domain error hierarchy.

Services raise these; the API layer maps each class to an HTTP status and a stable,
machine-readable `code` in the error envelope. Messages must be safe to show to users.
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    code: str = "domain_error"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.details = details or {}


class NotFoundError(DomainError):
    code = "not_found"


class ValidationFailedError(DomainError):
    code = "validation_failed"


class ConflictError(DomainError):
    code = "conflict"


class AuthenticationError(DomainError):
    code = "unauthenticated"


class PermissionDeniedError(DomainError):
    code = "forbidden"


class RateLimitedError(DomainError):
    code = "rate_limited"

    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message, details={"retryAfterSeconds": retry_after_seconds})
        self.retry_after_seconds = retry_after_seconds


class ServiceUnavailableError(DomainError):
    code = "service_unavailable"
