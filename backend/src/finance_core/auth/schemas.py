from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from pydantic import EmailStr, Field, SecretStr, field_validator

from finance_core.auth.passwords import MAX_PASSWORD_LENGTH
from finance_core.schemas import ApiInput, ApiModel
from finance_core.users.schemas import (
    MeView,
    validate_currency,
    validate_locale,
    validate_timezone,
)


class RegisterRequest(ApiInput):
    email: EmailStr
    password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)
    display_name: str = Field(min_length=1, max_length=100)
    base_currency: str = "INR"
    timezone: str = "Asia/Kolkata"
    locale: str = "en-IN"

    @field_validator("base_currency")
    @classmethod
    def _check_currency(cls, value: str) -> str:
        return validate_currency(value)

    @field_validator("timezone")
    @classmethod
    def _check_timezone(cls, value: str) -> str:
        return validate_timezone(value)

    @field_validator("locale")
    @classmethod
    def _check_locale(cls, value: str) -> str:
        return validate_locale(value)


class LoginRequest(ApiInput):
    email: EmailStr
    password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)


class PasswordChange(ApiInput):
    """A signed-in user replacing their password; the current one proves it is them."""

    current_password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: SecretStr = Field(max_length=MAX_PASSWORD_LENGTH)


class SessionView(ApiModel):
    """One signed-in browser or device, as the user sees it in Settings → Security."""

    id: uuid.UUID
    device: str = Field(description='Best guess from the User-Agent, e.g. "Chrome on Windows".')
    ip_address: str | None
    created_at: datetime
    last_seen_at: datetime = Field(description="Refreshed at most once an hour.")
    is_current: bool = Field(description="True for the session making this request.")


class RevokedSessionsView(ApiModel):
    """How many sessions a "sign out all other devices" request signed out."""

    revoked: int


@dataclass(frozen=True, slots=True)
class ClientInfo:
    ip_address: str | None
    user_agent: str | None


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller. Everything downstream is scoped by `user_id`."""

    user_id: uuid.UUID
    session_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class AuthResult:
    me: MeView
    token: str
    expires_at: datetime
