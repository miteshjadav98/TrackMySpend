"""Transaction service: the only code path that writes financial records.

REST endpoints, the chat agent, and (later) MCP tools all call this service, so validation,
idempotency, auditing, and cache invalidation are implemented exactly once.
"""

from __future__ import annotations

import base64
import binascii
import dataclasses
import json
import uuid
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Select, and_, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError

from finance_core.audit.service import Actor, record_audit
from finance_core.cache.primitives import UserDataGeneration
from finance_core.categories.models import Category
from finance_core.categories.service import CategoryService
from finance_core.clock import Clock
from finance_core.dates import EARLIEST_ALLOWED_DATE
from finance_core.errors import ConflictError, NotFoundError, ValidationFailedError
from finance_core.ids import uuid7
from finance_core.money import (
    SUPPORTED_CURRENCIES,
    MoneyError,
    exponent,
    format_money,
    from_minor,
    to_minor,
)
from finance_core.transactions.models import Transaction
from finance_core.transactions.schemas import (
    CategoryRef,
    NewTransaction,
    TransactionCreate,
    TransactionPage,
    TransactionQuery,
    TransactionUpdate,
    TransactionView,
)
from finance_core.users.context import UserContext

MAX_PAGE_SIZE = 100
MAX_BATCH = 20


def to_view(row: Transaction, category: Category | None, locale: str = "en-IN") -> TransactionView:
    return TransactionView(
        id=row.id,
        type=row.type,  # type: ignore[arg-type]
        amount=from_minor(row.amount_minor, row.currency),
        amount_minor=row.amount_minor,
        currency=row.currency,
        amount_formatted=format_money(row.amount_minor, row.currency, locale),
        occurred_on=row.occurred_on,
        category=(
            CategoryRef(id=category.id, slug=category.slug, name=category.name, icon=category.icon)
            if category
            else None
        ),
        description=row.description,
        merchant=row.merchant,
        payment_method=row.payment_method,  # type: ignore[arg-type]
        notes=row.notes,
        source=row.source,  # type: ignore[arg-type]
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _encode_cursor(occurred_on: date, row_id: uuid.UUID) -> str:
    raw = json.dumps({"d": occurred_on.isoformat(), "i": str(row_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[date, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return date.fromisoformat(data["d"]), uuid.UUID(data["i"])
    except (ValueError, KeyError, TypeError, binascii.Error, json.JSONDecodeError):
        raise ValidationFailedError("Invalid pagination cursor", details={"field": "cursor"}) from None


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.split())
    return value or None


def _audit_snapshot(row: Transaction | NewTransaction) -> dict[str, Any]:
    return {
        "type": row.type,
        "amountMinor": row.amount_minor,
        "currency": row.currency,
        "occurredOn": row.occurred_on.isoformat(),
        "categoryId": str(row.category_id) if row.category_id else None,
    }


class TransactionService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock,
        generation: UserDataGeneration | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._generation = generation
        self._categories = CategoryService(session)

    # -- validation -----------------------------------------------------------------------

    async def resolve(self, ctx: UserContext, data: TransactionCreate) -> NewTransaction:
        """Validate and normalise input into a persistable transaction.

        Raises `ValidationFailedError` with `details.field` set, which the agent turns
        into a focused clarification question instead of a generic error.
        """
        currency = (data.currency or ctx.base_currency).upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise ValidationFailedError(
                f"Unsupported currency: {currency}", details={"field": "currency"}
            )
        try:
            amount_minor = to_minor(data.amount, currency)
        except MoneyError as exc:
            raise ValidationFailedError(str(exc), details={"field": "amount"}) from None

        today = ctx.today(self._clock)
        occurred_on = data.occurred_on or today
        if occurred_on > today:
            raise ValidationFailedError(
                "The date can't be in the future.", details={"field": "occurredOn"}
            )
        if occurred_on < EARLIEST_ALLOWED_DATE:
            raise ValidationFailedError(
                "That date is too far in the past.", details={"field": "occurredOn"}
            )

        category_id: uuid.UUID | None = None
        if data.category_id is not None:
            category = await self._categories.get_visible(ctx.user_id, data.category_id)
            if category.kind != data.type:
                raise ValidationFailedError(
                    f"'{category.name}' is an {category.kind} category.",
                    details={"field": "categoryId"},
                )
            category_id = category.id

        return NewTransaction(
            type=data.type,
            amount_minor=amount_minor,
            currency=currency,
            occurred_on=occurred_on,
            category_id=category_id,
            description=_clean_text(data.description),
            merchant=_clean_text(data.merchant),
            payment_method=data.payment_method,
            notes=_clean_text(data.notes),
        )

    # -- writes ---------------------------------------------------------------------------

    async def create(
        self,
        ctx: UserContext,
        data: TransactionCreate,
        *,
        source: Literal["chat", "manual", "import", "api"] = "manual",
        idempotency_key: str | None = None,
        actor: Actor = "user",
        request_id: str | None = None,
    ) -> tuple[TransactionView, bool]:
        """Create one transaction. Returns (view, created); created=False on idempotent replay."""
        new = await self.resolve(ctx, data)
        [(view, created)] = await self.create_resolved(
            ctx,
            [(new, idempotency_key)],
            source=source,
            actor=actor,
            request_id=request_id,
            strict_idempotency=True,
        )
        return view, created

    async def create_resolved(
        self,
        ctx: UserContext,
        items: Sequence[tuple[NewTransaction, str | None]],
        *,
        source: Literal["chat", "manual", "import", "api"],
        source_ref: str | None = None,
        actor: Actor = "user",
        request_id: str | None = None,
        strict_idempotency: bool = False,
    ) -> list[tuple[TransactionView, bool]]:
        """Insert a batch atomically. Each item may carry an idempotency key.

        A repeated key returns the existing row instead of inserting a duplicate. With
        `strict_idempotency`, reusing a key for *different* data is a 409, which is what
        an HTTP client needs; agent replays are lenient because the model may phrase the
        same draft slightly differently on a retried turn.
        """
        if not items:
            return []
        if len(items) > MAX_BATCH:
            raise ValidationFailedError(f"At most {MAX_BATCH} transactions at once")
        results: list[tuple[uuid.UUID, bool]] = []
        for new, key in items:
            inserted_id = await self._session.scalar(
                pg_insert(Transaction)
                .values(
                    id=uuid7(),
                    user_id=ctx.user_id,
                    type=new.type,
                    amount_minor=new.amount_minor,
                    currency=new.currency,
                    occurred_on=new.occurred_on,
                    category_id=new.category_id,
                    description=new.description,
                    merchant=new.merchant,
                    payment_method=new.payment_method,
                    notes=new.notes,
                    source=source,
                    source_ref=source_ref,
                    idempotency_key=key,
                    version=1,
                )
                .on_conflict_do_nothing(index_elements=["user_id", "idempotency_key"])
                .returning(Transaction.id)
            )
            if inserted_id is not None:
                record_audit(
                    self._session, user_id=ctx.user_id, actor=actor, action="transaction.created",
                    entity_type="transaction", entity_id=inserted_id,
                    data={**_audit_snapshot(new), "source": source}, request_id=request_id,
                )  # fmt: skip
                results.append((inserted_id, True))
                continue
            existing = await self._session.scalar(
                select(Transaction).where(
                    Transaction.user_id == ctx.user_id, Transaction.idempotency_key == key
                )
            )
            assert existing is not None  # a conflict implies the row exists
            if strict_idempotency and _audit_snapshot(existing) != _audit_snapshot(new):
                await self._session.rollback()
                raise ConflictError(
                    "This Idempotency-Key was already used for a different transaction.",
                    code="idempotency_key_reused",
                )
            results.append((existing.id, False))

        await self._session.commit()
        if any(created for _, created in results) and self._generation is not None:
            await self._generation.bump(ctx.user_id)

        views = await self._views([row_id for row_id, _ in results], ctx.locale)
        return [(views[row_id], created) for row_id, created in results]

    async def update(
        self,
        ctx: UserContext,
        transaction_id: uuid.UUID,
        patch: TransactionUpdate,
        *,
        actor: Actor = "user",
        request_id: str | None = None,
    ) -> TransactionView:
        row = await self._live_row(ctx.user_id, transaction_id)
        if row.version != patch.version:
            raise ConflictError(
                "This transaction was changed elsewhere. Reload and try again.",
                code="version_conflict",
                details={"currentVersion": row.version},
            )
        fields = patch.model_fields_set - {"version"}
        if not fields:
            return (await self._views([row.id], ctx.locale))[row.id]

        merged = TransactionCreate(
            type=patch.type if "type" in fields and patch.type else row.type,  # type: ignore[arg-type]
            amount=(
                patch.amount
                if "amount" in fields and patch.amount is not None
                else from_minor(row.amount_minor, row.currency)
            ),
            currency=patch.currency if "currency" in fields and patch.currency else row.currency,
            occurred_on=(
                patch.occurred_on
                if "occurred_on" in fields and patch.occurred_on
                else row.occurred_on
            ),
            category_id=patch.category_id if "category_id" in fields else row.category_id,
            description=patch.description if "description" in fields else row.description,
            merchant=patch.merchant if "merchant" in fields else row.merchant,
            payment_method=(
                patch.payment_method if "payment_method" in fields else row.payment_method  # type: ignore[arg-type]
            ),
            notes=patch.notes if "notes" in fields else row.notes,
        )
        if merged.type != row.type and "category_id" not in fields:
            merged = merged.model_copy(update={"category_id": None})  # old category is the wrong kind
        resolved = await self._resolve_for_update(ctx, merged, row)

        before = _audit_snapshot(row)
        changes: dict[str, list[Any]] = {}
        for attr in ("type", "amount_minor", "currency", "occurred_on", "category_id",
                     "description", "merchant", "payment_method", "notes"):  # fmt: skip
            old, new = getattr(row, attr), getattr(resolved, attr)
            if old != new:
                changes[attr] = [str(old) if old is not None else None, str(new) if new is not None else None]
                setattr(row, attr, new)
        if not changes:
            return (await self._views([row.id], ctx.locale))[row.id]
        record_audit(
            self._session, user_id=ctx.user_id, actor=actor, action="transaction.updated",
            entity_type="transaction", entity_id=row.id,
            data={"before": before, "changes": changes}, request_id=request_id,
        )  # fmt: skip
        try:
            await self._session.commit()
        except StaleDataError:
            await self._session.rollback()
            raise ConflictError(
                "This transaction was changed elsewhere. Reload and try again.",
                code="version_conflict",
            ) from None
        if self._generation is not None:
            await self._generation.bump(ctx.user_id)
        return (await self._views([row.id], ctx.locale))[row.id]

    async def _resolve_for_update(
        self, ctx: UserContext, merged: TransactionCreate, row: Transaction
    ) -> NewTransaction:
        # An edit may legitimately keep an existing future-dated or old row's date
        # (e.g. after a timezone change); only re-validate the date when it changes.
        if merged.occurred_on == row.occurred_on:
            resolved = await self.resolve(ctx, merged.model_copy(update={"occurred_on": None}))
            return dataclasses.replace(resolved, occurred_on=row.occurred_on)
        return await self.resolve(ctx, merged)

    async def delete(
        self,
        ctx: UserContext,
        transaction_id: uuid.UUID,
        *,
        actor: Actor = "user",
        request_id: str | None = None,
    ) -> None:
        """Soft delete: excluded from every list and total, restorable, fully audited."""
        row = await self._live_row(ctx.user_id, transaction_id)
        row.deleted_at = self._clock.now()
        record_audit(
            self._session, user_id=ctx.user_id, actor=actor, action="transaction.deleted",
            entity_type="transaction", entity_id=row.id, data={"before": _audit_snapshot(row)},
            request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        if self._generation is not None:
            await self._generation.bump(ctx.user_id)

    async def restore(
        self,
        ctx: UserContext,
        transaction_id: uuid.UUID,
        *,
        actor: Actor = "user",
        request_id: str | None = None,
    ) -> TransactionView:
        row = await self._session.scalar(
            select(Transaction).where(
                Transaction.id == transaction_id,
                Transaction.user_id == ctx.user_id,
                Transaction.deleted_at.is_not(None),
            )
        )
        if row is None:
            raise NotFoundError("Transaction not found")
        row.deleted_at = None
        record_audit(
            self._session, user_id=ctx.user_id, actor=actor, action="transaction.restored",
            entity_type="transaction", entity_id=row.id, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        if self._generation is not None:
            await self._generation.bump(ctx.user_id)
        return (await self._views([row.id], ctx.locale))[row.id]

    # -- reads ----------------------------------------------------------------------------

    async def get(self, ctx: UserContext, transaction_id: uuid.UUID) -> TransactionView:
        row = await self._live_row(ctx.user_id, transaction_id)
        return (await self._views([row.id], ctx.locale))[row.id]

    async def find_by_source_ref(self, ctx: UserContext, source_ref: str) -> list[TransactionView]:
        ids = (
            await self._session.scalars(
                select(Transaction.id)
                .where(
                    Transaction.user_id == ctx.user_id,
                    Transaction.source_ref == source_ref,
                    Transaction.deleted_at.is_(None),
                )
                .order_by(Transaction.created_at, Transaction.id)
            )
        ).all()
        views = await self._views(list(ids), ctx.locale)
        return [views[row_id] for row_id in ids]

    async def search(self, ctx: UserContext, query: TransactionQuery) -> TransactionPage:
        limit = max(1, min(query.limit, MAX_PAGE_SIZE))
        stmt: Select[tuple[Transaction, Category | None]] = (
            select(Transaction, Category)
            .outerjoin(Category, Category.id == Transaction.category_id)
            .where(Transaction.user_id == ctx.user_id, Transaction.deleted_at.is_(None))
        )
        if query.type:
            stmt = stmt.where(Transaction.type == query.type)
        if query.category_id:
            stmt = stmt.where(Transaction.category_id == query.category_id)
        if query.date_from:
            stmt = stmt.where(Transaction.occurred_on >= query.date_from)
        if query.date_to:
            stmt = stmt.where(Transaction.occurred_on <= query.date_to)
        if query.text:
            pattern = f"%{_escape_like(query.text.strip()[:100])}%"
            stmt = stmt.where(
                or_(
                    Transaction.description.ilike(pattern, escape="\\"),
                    Transaction.merchant.ilike(pattern, escape="\\"),
                    Transaction.notes.ilike(pattern, escape="\\"),
                    Category.name.ilike(pattern, escape="\\"),
                )
            )
        # Amount filters and "largest" ordering only make sense within one currency.
        currency = (query.currency or "").upper() or None
        if query.min_amount is not None or query.max_amount is not None or query.sort == "largest":
            currency = currency or ctx.base_currency
        if currency:
            if currency not in SUPPORTED_CURRENCIES:
                raise ValidationFailedError("Unsupported currency", details={"field": "currency"})
            stmt = stmt.where(Transaction.currency == currency)
            scale = Decimal(10) ** exponent(currency)
            if query.min_amount is not None:
                stmt = stmt.where(Transaction.amount_minor >= int(query.min_amount * scale))
            if query.max_amount is not None:
                stmt = stmt.where(Transaction.amount_minor <= int(query.max_amount * scale))

        if query.sort == "largest":
            stmt = stmt.order_by(Transaction.amount_minor.desc(), Transaction.id.desc())
        else:
            if query.cursor:
                cursor_date, cursor_id = _decode_cursor(query.cursor)
                stmt = stmt.where(
                    tuple_(Transaction.occurred_on, Transaction.id) < tuple_(cursor_date, cursor_id)
                )
            stmt = stmt.order_by(Transaction.occurred_on.desc(), Transaction.id.desc())

        rows = (await self._session.execute(stmt.limit(limit + 1))).all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [to_view(row, category, ctx.locale) for row, category in rows]
        next_cursor = None
        if has_more and query.sort == "recent" and rows:
            last = rows[-1][0]
            next_cursor = _encode_cursor(last.occurred_on, last.id)
        return TransactionPage(items=items, next_cursor=next_cursor)

    # -- helpers --------------------------------------------------------------------------

    async def _live_row(self, user_id: uuid.UUID, transaction_id: uuid.UUID) -> Transaction:
        # Ownership is part of the WHERE clause: another user's id is simply "not found".
        row = await self._session.scalar(
            select(Transaction).where(
                and_(
                    Transaction.id == transaction_id,
                    Transaction.user_id == user_id,
                    Transaction.deleted_at.is_(None),
                )
            )
        )
        if row is None:
            raise NotFoundError("Transaction not found")
        return row

    async def _views(self, ids: list[uuid.UUID], locale: str) -> dict[uuid.UUID, TransactionView]:
        if not ids:
            return {}
        rows = (
            await self._session.execute(
                select(Transaction, Category)
                .outerjoin(Category, Category.id == Transaction.category_id)
                .where(Transaction.id.in_(ids))
            )
        ).all()
        return {row.id: to_view(row, category, locale) for row, category in rows}
