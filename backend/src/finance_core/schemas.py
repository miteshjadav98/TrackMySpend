"""Base Pydantic models for every public contract.

JSON is camelCase (TypeScript convention); Python stays snake_case. These models are the
single source of truth: FastAPI publishes them as OpenAPI, and the frontend's TypeScript
types are generated from that document, so the two sides cannot drift.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from finance_core.money import format_money, from_minor


class ApiModel(BaseModel):
    """Response / payload model."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
        from_attributes=True,
    )


class ApiInput(ApiModel):
    """Request model: unknown fields are rejected rather than silently ignored."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def response_model_names() -> set[str]:
    """Names of every response (non-input) model, for OpenAPI post-processing."""
    names: set[str] = set()
    stack: list[type[ApiModel]] = [ApiModel]
    while stack:
        for subclass in stack.pop().__subclasses__():
            stack.append(subclass)
            if not issubclass(subclass, ApiInput):
                names.add(subclass.__name__)
    return names


class MoneyAmount(ApiModel):
    """An exact amount. `amount` is a decimal string; never parse it as a float."""

    amount: Decimal
    amount_minor: int
    currency: str
    formatted: str

    @classmethod
    def of(cls, minor: int, currency: str, locale: str = "en-IN") -> MoneyAmount:
        return cls(
            amount=from_minor(minor, currency),
            amount_minor=minor,
            currency=currency,
            formatted=format_money(minor, currency, locale),
        )
