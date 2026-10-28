"""Account service: the only code that reads or writes a user's accounts.

The rules it enforces:
- Two active accounts of one user never share a name, ignoring case (409 `account_exists`).
- A new account's currency is the user's base currency unless they pick a supported one (422).
- A user has at most `MAX_ACTIVE_ACCOUNTS` active accounts (422).
- An account's currency never changes after it is created (`AccountUpdate` has no currency).
- Another user's account is "not found" (404), exactly like an id that does not exist.
- Every change is audited in the same database transaction: `account.created`,
  `account.updated` (name or kind), `account.archived` and `account.unarchived`.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.accounts.models import ACTIVE_NAME_INDEX, Account
from finance_core.accounts.schemas import AccountCreate, AccountUpdate, AccountView
from finance_core.audit.service import record_audit
from finance_core.errors import ConflictError, NotFoundError, ValidationFailedError
from finance_core.ids import uuid7
from finance_core.money import SUPPORTED_CURRENCIES
from finance_core.users.context import UserContext

# Enough for every bank, card and wallet a person really uses; it keeps pickers short and
# bounds the list, which is returned whole rather than paged.
MAX_ACTIVE_ACCOUNTS = 50


def to_view(account: Account) -> AccountView:
    return AccountView.model_validate(account)


def _name_taken() -> ConflictError:
    return ConflictError(
        "You already have an active account with this name.", code="account_exists"
    )


def _violated_constraint(error: IntegrityError) -> str | None:
    """The name of the constraint or unique index Postgres reported, if it named one."""
    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None)


def _currency_for_new_account(requested: str | None, ctx: UserContext) -> str:
    currency = (requested or ctx.base_currency).upper()
    if currency not in SUPPORTED_CURRENCIES:
        raise ValidationFailedError(
            f"Unsupported currency: {currency}", details={"field": "currency"}
        )
    return currency


class AccountService:
    """Lists, adds, renames, re-kinds, archives and unarchives one user's accounts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_accounts(
        self, ctx: UserContext, *, include_archived: bool = False
    ) -> list[AccountView]:
        """The user's accounts, active ones first, then by name."""
        query = select(Account).where(Account.user_id == ctx.user_id)
        if not include_archived:
            query = query.where(Account.is_archived.is_(False))
        query = query.order_by(Account.is_archived, func.lower(Account.name), Account.id)
        return [to_view(row) for row in (await self._session.scalars(query)).all()]

    async def create(
        self, ctx: UserContext, data: AccountCreate, *, request_id: str | None = None
    ) -> AccountView:
        await self._ensure_name_is_free(ctx.user_id, data.name)
        await self._ensure_room_for_another_active_account(ctx.user_id)
        account = Account(
            id=uuid7(),  # set here, not at flush, so the audit event can name it
            user_id=ctx.user_id,
            name=data.name,
            kind=data.kind,
            currency=_currency_for_new_account(data.currency, ctx),
            is_archived=False,
        )
        self._session.add(account)
        self._audit(
            ctx, "account.created", account, request_id=request_id,
            data={"name": account.name, "kind": account.kind, "currency": account.currency},
        )  # fmt: skip
        await self._commit()
        await self._session.refresh(account)  # the database set created_at and updated_at
        return to_view(account)

    async def update(
        self,
        ctx: UserContext,
        account_id: uuid.UUID,
        patch: AccountUpdate,
        *,
        request_id: str | None = None,
    ) -> AccountView:
        """Rename, re-kind, archive or unarchive one of the user's accounts."""
        account = await self._owned_account(ctx.user_id, account_id)
        name = account.name if patch.name is None else patch.name
        kind = account.kind if patch.kind is None else patch.kind
        archived = account.is_archived if patch.is_archived is None else patch.is_archived

        changes = {
            field: [old, new]
            for field, old, new in (("name", account.name, name), ("kind", account.kind, kind))
            if old != new
        }
        archive_flips = archived != account.is_archived
        if not changes and not archive_flips:
            return to_view(account)  # nothing to save, nothing to audit

        if not archived:  # the account is active after this edit, so its name must be free
            await self._ensure_name_is_free(ctx.user_id, name, other_than=account.id)
        if account.is_archived and not archived:  # unarchiving adds an active account
            await self._ensure_room_for_another_active_account(ctx.user_id)

        if changes:
            self._audit(ctx, "account.updated", account, data={"changes": changes},
                        request_id=request_id)  # fmt: skip
        if archive_flips:
            action = "account.archived" if archived else "account.unarchived"
            self._audit(ctx, action, account, request_id=request_id)
        account.name, account.kind, account.is_archived = name, kind, archived
        await self._commit()
        await self._session.refresh(account)  # the database set updated_at
        return to_view(account)

    async def get(self, ctx: UserContext, account_id: uuid.UUID, *, field: str) -> AccountView:
        """One of the user's accounts, archived or not (404 otherwise)."""
        return to_view(await self._owned_account(ctx.user_id, account_id, field=field))

    async def pick_for_transaction(
        self, ctx: UserContext, account_id: uuid.UUID, *, field: str
    ) -> AccountView:
        """The account a transaction is being tagged with, if the user may pick it.

        Two checks, in order: it is one of the user's own accounts (404 otherwise, exactly
        like an id that does not exist), and it is active (422: archived accounts stay on old
        transactions but are not picked for new ones). `field` is the request field that
        named the account, so an error points at it.
        """
        account = await self._owned_account(ctx.user_id, account_id, field=field)
        if account.is_archived:
            raise ValidationFailedError(
                f"'{account.name}' is archived. Unarchive it in Settings or pick another account.",
                details={"field": field},
            )
        return to_view(account)

    async def _owned_account(
        self, user_id: uuid.UUID, account_id: uuid.UUID, *, field: str | None = None
    ) -> Account:
        # Ownership is part of the WHERE clause: another user's id is simply "not found".
        account = await self._session.scalar(
            select(Account).where(Account.id == account_id, Account.user_id == user_id)
        )
        if account is None:
            raise NotFoundError("Account not found", details={"field": field} if field else None)
        return account

    # -- rules ----------------------------------------------------------------------------

    async def _ensure_name_is_free(
        self, user_id: uuid.UUID, name: str, *, other_than: uuid.UUID | None = None
    ) -> None:
        """No other active account of this user has this name, ignoring case."""
        query = select(Account.id).where(
            Account.user_id == user_id,
            Account.is_archived.is_(False),
            func.lower(Account.name) == func.lower(name),
        )
        if other_than is not None:
            query = query.where(Account.id != other_than)
        if await self._session.scalar(query) is not None:
            raise _name_taken()

    async def _ensure_room_for_another_active_account(self, user_id: uuid.UUID) -> None:
        active = await self._session.scalar(
            select(func.count())
            .select_from(Account)
            .where(Account.user_id == user_id, Account.is_archived.is_(False))
        )
        if (active or 0) >= MAX_ACTIVE_ACCOUNTS:
            raise ValidationFailedError(
                f"You can have at most {MAX_ACTIVE_ACCOUNTS} active accounts. "
                "Archive one you no longer use first."
            )

    def _audit(
        self,
        ctx: UserContext,
        action: str,
        account: Account,
        *,
        data: dict[str, Any] | None = None,
        request_id: str | None,
    ) -> None:
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action=action,
            entity_type="account", entity_id=account.id, data=data, request_id=request_id,
        )  # fmt: skip

    async def _commit(self) -> None:
        # The unique index on active names is the final word: two requests racing past
        # `_ensure_name_is_free` still cannot both save, and the loser gets the same 409.
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            if _violated_constraint(error) == ACTIVE_NAME_INDEX:
                raise _name_taken() from None
            raise
