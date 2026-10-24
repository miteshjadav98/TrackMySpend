"""FastAPI application factory.

Run with `python -m finance_api.serve` (or `uvicorn finance_api.main:create_app --factory`).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from pydantic import TypeAdapter

from finance_api.container import lifespan
from finance_api.errors import register_exception_handlers
from finance_api.middleware import RequestContextMiddleware
from finance_api.routes import ROUTERS
from finance_core.agents.events import TurnEvent
from finance_core.clock import Clock
from finance_core.config import Settings, get_settings
from finance_core.llm import LLMClient
from finance_core.observability import configure_logging

API_VERSION = "0.1.0"


def _install_openapi(app: FastAPI) -> None:
    """Add the streamed `TurnEvent` union to the schema so clients can generate its types."""

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            separate_input_output_schemas=False,
        )
        event_schema = TypeAdapter(TurnEvent).json_schema(
            by_alias=True, ref_template="#/components/schemas/{model}", mode="serialization"
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, definition in event_schema.pop("$defs", {}).items():
            components.setdefault(name, definition)
        components["TurnEvent"] = event_schema
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]


def create_app(
    settings: Settings | None = None,
    *,
    llm: LLMClient | None = None,
    clock: Clock | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    app = FastAPI(
        title="MoneyMoney API",
        version=API_VERSION,
        description="Personal finance assistant: chat, transactions, and summaries.",
        lifespan=lifespan,
        openapi_url="/api/openapi.json",
        docs_url=None if settings.environment == "production" else "/api/docs",
        redoc_url=None,
        separate_input_output_schemas=False,
    )
    app.state.settings = settings
    if llm is not None:
        app.state.llm_override = llm
    if clock is not None:
        app.state.clock = clock

    register_exception_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key", "X-Request-ID", "Authorization"],
        expose_headers=["X-Request-ID", "Retry-After"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware, settings=settings)  # outermost
    for router in ROUTERS:
        app.include_router(router)
    _install_openapi(app)
    return app
