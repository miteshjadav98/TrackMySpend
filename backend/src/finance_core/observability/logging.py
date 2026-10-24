"""Structured logging.

JSON lines in the shape Google Cloud Logging understands (`severity`, `message`), with
request/user/conversation ids attached from context variables so every line of a request
can be correlated. Never log message content, statements, or credentials: log ids,
sizes, decisions, and timings instead.
"""

from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
user_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
conversation_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "conversation_id", default=None
)

_STANDARD_ATTRS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
    | {"message", "asctime", "color_message", "taskName"}
)


def _context() -> dict[str, str]:
    values = {
        "requestId": request_id_var.get(),
        "userId": user_id_var.get(),
        "conversationId": conversation_id_var.get(),
    }
    return {key: value for key, value in values.items() if value}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **_context(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Readable single-line logs for local development."""

    def format(self, record: logging.LogRecord) -> str:
        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and not key.startswith("_")
        }
        context = _context()
        suffix = " ".join(f"{k}={v}" for k, v in {**context, **extras}.items())
        line = f"{record.levelname:<7} {record.name}: {record.getMessage()}"
        if suffix:
            line = f"{line}  [{suffix}]"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else ConsoleFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Uvicorn's access log duplicates our request log; HTTP client logs are noisy.
    for noisy in ("uvicorn.access", "httpx", "httpcore", "google_genai", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
