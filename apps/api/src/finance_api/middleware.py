"""Request context, access logging, and security headers.

A pure ASGI middleware (not BaseHTTPMiddleware) so streaming responses pass through
untouched and context variables propagate into the request's tasks.
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from finance_core.config import Settings
from finance_core.observability import conversation_id_var, request_id_var, user_id_var

logger = logging.getLogger("finance_api.access")

_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp, *, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    def _request_id(self, scope: Scope) -> str:
        for name, value in scope.get("headers", []):
            if name == b"x-request-id":
                candidate = str(value.decode("latin-1"))
                if _REQUEST_ID.match(candidate):
                    return candidate
            if name == b"x-cloud-trace-context":  # Google front end trace id
                trace = str(value.decode("latin-1")).split("/", 1)[0]
                if _REQUEST_ID.match(trace):
                    return trace
        return uuid.uuid4().hex

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = self._request_id(scope)
        tokens = (
            request_id_var.set(request_id),
            user_id_var.set(None),
            conversation_id_var.set(None),
        )
        started = time.perf_counter()
        status_holder = {"status": 500}
        secure = self.settings.cookie_secure

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                headers = MutableHeaders(scope=message)
                headers["x-request-id"] = request_id
                headers["x-content-type-options"] = "nosniff"
                headers["x-frame-options"] = "DENY"
                headers["referrer-policy"] = "strict-origin-when-cross-origin"
                if "cache-control" not in headers:
                    headers["cache-control"] = "no-store"  # financial data: never cache
                if secure:
                    headers["strict-transport-security"] = "max-age=31536000; includeSubDomains"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            path = scope.get("path", "")
            if path not in ("/healthz", "/readyz"):
                logger.info(
                    "request",
                    extra={
                        "httpMethod": scope.get("method"),
                        "path": path,  # never the query string: it can carry search text
                        "status": status_holder["status"],
                        "durationMs": duration_ms,
                    },
                )
            for var, token in zip(
                (request_id_var, user_id_var, conversation_id_var), tokens, strict=True
            ):
                var.reset(token)
