from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.errors import NotFoundError
from finance_core.users.context import UserContext
from finance_core.users.models import FinancialProfile, User
from finance_core.users.schemas import MeView, ProfileUpdate, ProfileView, UserView


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _load(self, user_id: uuid.UUID) -> tuple[User, FinancialProfile]:
        row = (
            await self._session.execute(
                select(User, FinancialProfile)
                .join(FinancialProfile, FinancialProfile.user_id == User.id)
                .where(User.id == user_id, User.status == "active")
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Account not found")
        return row[0], row[1]

    async def context(self, user_id: uuid.UUID) -> UserContext:
        profile = await self._session.get(FinancialProfile, user_id)
        if profile is None:
            raise NotFoundError("Account not found")
        return UserContext(
            user_id=user_id,
            base_currency=profile.base_currency,
            timezone=profile.timezone,
            locale=profile.locale,
        )

    async def me(self, user_id: uuid.UUID) -> MeView:
        user, profile = await self._load(user_id)
        return MeView(
            user=UserView.model_validate(user), profile=ProfileView.model_validate(profile)
        )

    async def update_profile(
        self, user_id: uuid.UUID, update: ProfileUpdate, *, request_id: str | None = None
    ) -> MeView:
        user, profile = await self._load(user_id)
        changes: dict[str, list[str]] = {}
        if update.display_name is not None and update.display_name != user.display_name:
            changes["displayName"] = [user.display_name, update.display_name]
            user.display_name = update.display_name
        for field, attr in (
            ("base_currency", "base_currency"),
            ("timezone", "timezone"),
            ("locale", "locale"),
        ):
            value = getattr(update, field)
            if value is not None and value != getattr(profile, attr):
                changes[field] = [getattr(profile, attr), value]
                setattr(profile, attr, value)
        if changes:
            record_audit(
                self._session,
                user_id=user_id,
                actor="user",
                action="profile.updated",
                entity_type="profile",
                entity_id=user_id,
                data={"changes": changes},
                request_id=request_id,
            )
            await self._session.commit()
        return MeView(
            user=UserView.model_validate(user), profile=ProfileView.model_validate(profile)
        )
