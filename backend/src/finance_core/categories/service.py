from __future__ import annotations

import re
import uuid
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.categories.defaults import CategoryKind, infer_category_slug
from finance_core.categories.models import Category
from finance_core.categories.schemas import CategoryCreate, CategoryView
from finance_core.errors import ConflictError, NotFoundError, ValidationFailedError
from finance_core.transactions.models import Transaction

MAX_CUSTOM_CATEGORIES = 100


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return slug[:48]


def to_view(category: Category) -> CategoryView:
    return CategoryView(
        id=category.id,
        slug=category.slug,
        name=category.name,
        kind=category.kind,
        icon=category.icon,
        is_system=category.user_id is None,
    )


class CategoryService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _visible(self, user_id: uuid.UUID):  # type: ignore[no-untyped-def]
        return or_(Category.user_id.is_(None), Category.user_id == user_id)

    async def list_visible(
        self, user_id: uuid.UUID, kind: CategoryKind | None = None
    ) -> list[CategoryView]:
        query = select(Category).where(self._visible(user_id), Category.is_archived.is_(False))
        if kind is not None:
            query = query.where(Category.kind == kind)
        query = query.order_by(Category.kind, Category.sort_order, Category.name)
        return [to_view(row) for row in (await self._session.scalars(query)).all()]

    async def get_visible(self, user_id: uuid.UUID, category_id: uuid.UUID) -> Category:
        category = await self._session.scalar(
            select(Category).where(Category.id == category_id, self._visible(user_id))
        )
        if category is None or category.is_archived:
            raise NotFoundError("Category not found", details={"field": "categoryId"})
        return category

    async def by_slug(self, user_id: uuid.UUID, slug: str, kind: CategoryKind) -> Category | None:
        """User's own category wins over a system one with the same slug."""
        rows = (
            await self._session.scalars(
                select(Category).where(
                    Category.slug == slug,
                    Category.kind == kind,
                    Category.is_archived.is_(False),
                    self._visible(user_id),
                )
            )
        ).all()
        own = [row for row in rows if row.user_id is not None]
        if own:
            return own[0]
        return rows[0] if rows else None

    async def match(self, user_id: uuid.UUID, text: str, kind: CategoryKind) -> Category | None:
        """Interpret free text as a category: exact slug/name, then keyword inference."""
        cleaned = text.strip()
        if not cleaned:
            return None
        lowered = cleaned.lower()
        candidates = await self.list_visible(user_id, kind)
        for view in candidates:
            if lowered in (view.slug, view.name.lower(), slugify(view.name)):
                return await self.by_slug(user_id, view.slug, kind)
        for view in candidates:  # "Food" matches "Food & Dining"
            if re.search(rf"(?<![a-z]){re.escape(lowered)}(?![a-z])", view.name.lower()):
                return await self.by_slug(user_id, view.slug, kind)
        inferred = infer_category_slug(cleaned, kind)
        return await self.by_slug(user_id, inferred, kind) if inferred else None

    async def ranked_for_choice(
        self, user_id: uuid.UUID, kind: CategoryKind, today: date, *, limit: int = 8
    ) -> list[CategoryView]:
        """Options for a clarification question, most-used first (last 90 days)."""
        usage = dict(
            (
                await self._session.execute(
                    select(Transaction.category_id, func.count())
                    .where(
                        Transaction.user_id == user_id,
                        Transaction.deleted_at.is_(None),
                        Transaction.type == kind,
                        Transaction.occurred_on >= today - timedelta(days=90),
                        Transaction.category_id.is_not(None),
                    )
                    .group_by(Transaction.category_id)
                )
            ).all()
        )
        categories = await self.list_visible(user_id, kind)
        fallback = [c for c in categories if c.slug in ("other", "other_income")]
        regular = [c for c in categories if c not in fallback]
        regular.sort(key=lambda c: -usage.get(c.id, 0))  # stable: keeps default order on ties
        return regular[: max(1, limit - len(fallback))] + fallback

    async def create(
        self, user_id: uuid.UUID, data: CategoryCreate, *, request_id: str | None = None
    ) -> CategoryView:
        slug = slugify(data.name)
        if not slug:
            raise ValidationFailedError(
                "Category name needs letters or numbers", details={"field": "name"}
            )
        existing = await self.by_slug(user_id, slug, data.kind)
        if existing is not None:
            if existing.user_id is None:
                return to_view(existing)  # reuse the equivalent system category
            raise ConflictError(
                "You already have a category with this name", code="category_exists"
            )
        count = await self._session.scalar(
            select(func.count()).select_from(Category).where(Category.user_id == user_id)
        )
        if (count or 0) >= MAX_CUSTOM_CATEGORIES:
            raise ValidationFailedError("You have reached the maximum number of custom categories")
        category = Category(
            user_id=user_id,
            slug=slug,
            name=data.name.strip(),
            kind=data.kind,
            icon=data.icon or "tag",
            sort_order=500,
            is_archived=False,
        )
        self._session.add(category)
        await self._session.flush()
        record_audit(
            self._session, user_id=user_id, actor="user", action="category.created",
            entity_type="category", entity_id=category.id, data={"name": category.name, "kind": data.kind},
            request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        return to_view(category)
