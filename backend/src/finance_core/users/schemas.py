from __future__ import annotations

import re
import uuid
from datetime import datetime
from functools import lru_cache
from zoneinfo import available_timezones

from pydantic import Field, field_validator

from finance_core.money import SUPPORTED_CURRENCIES
from finance_core.schemas import ApiInput, ApiModel

_LOCALE_PATTERN = re.compile(r"^[a-z]{2,3}(-[A-Z]{2})?$")


@lru_cache(maxsize=1)
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def validate_timezone(value: str) -> str:
    if value not in _timezones():
        raise ValueError("Unknown timezone; use an IANA name such as Asia/Kolkata")
    return value


def validate_currency(value: str) -> str:
    code = value.strip().upper()
    if code not in SUPPORTED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {value}")
    return code


def validate_locale(value: str) -> str:
    if not _LOCALE_PATTERN.match(value):
        raise ValueError("Locale must look like en-IN")
    return value


class UserView(ApiModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime


class ProfileView(ApiModel):
    base_currency: str
    timezone: str
    locale: str


class MeView(ApiModel):
    user: UserView
    profile: ProfileView


class ProfileUpdate(ApiInput):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    base_currency: str | None = None
    timezone: str | None = None
    locale: str | None = None

    @field_validator("base_currency")
    @classmethod
    def _currency(cls, value: str | None) -> str | None:
        return validate_currency(value) if value is not None else None

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, value: str | None) -> str | None:
        return validate_timezone(value) if value is not None else None

    @field_validator("locale")
    @classmethod
    def _locale(cls, value: str | None) -> str | None:
        return validate_locale(value) if value is not None else None
