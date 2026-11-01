"""Friend service: the only code that reads or writes friends and friend invites.

The rules it enforces:
- A user adds, renames, re-emails and removes only their own friends; another user's friend or
  invite is "not found" (404), exactly like an id that does not exist.
- Names are trimmed and at most 80 characters; two friends may share a name, never an email
  (409 `friend_email_exists`). A user cannot add their own email (422).
- Giving a friend an email sends an invite to that address. It is matched by email, so an
  address with no account yet simply waits until someone signs up with it.
- Accepting an invite links both users: each ends up with a friend row pointing at the other.
  A linked friend's email is fixed (409 `friend_linked`).
- Every change is audited in the same database transaction as the change.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.audit.service import record_audit
from finance_core.errors import ConflictError, NotFoundError, ValidationFailedError
from finance_core.friends.models import (
    ACTIVE_EMAIL_INDEX,
    Friend,
    FriendInvite,
    SharedExpense,
    SharedExpenseShare,
)
from finance_core.friends.schemas import (
    FriendCreate,
    FriendInviteView,
    FriendUpdate,
    FriendView,
)
from finance_core.ids import uuid7
from finance_core.users.context import UserContext
from finance_core.users.models import User


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _email_taken() -> ConflictError:
    return ConflictError("You already have a friend with this email.", code="friend_email_exists")


def _violated_constraint(error: IntegrityError) -> str | None:
    diagnostics = getattr(error.orig, "diag", None)
    return getattr(diagnostics, "constraint_name", None)


class FriendService:
    """Lists, adds, changes and removes one user's friends, and answers their invites."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # -- friends --------------------------------------------------------------------------

    async def list_friends(self, ctx: UserContext) -> list[FriendView]:
        """The user's active friends, by name."""
        rows = (
            await self._session.scalars(
                select(Friend)
                .where(Friend.user_id == ctx.user_id, Friend.is_archived.is_(False))
                .order_by(func.lower(Friend.name), Friend.created_at, Friend.id)
            )
        ).all()
        statuses = await self._open_invite_statuses([row.id for row in rows])
        return [self._view(row, statuses.get(row.id)) for row in rows]

    async def add(
        self, ctx: UserContext, data: FriendCreate, *, request_id: str | None = None
    ) -> FriendView:
        """Add a friend; with an email, also invite whoever owns it."""
        email = _normalize_email(str(data.email)) if data.email else None
        if email:
            await self._ensure_email_is_usable(ctx, email)
        friend = Friend(
            id=uuid7(),  # set here, not at flush, so the audit event can name it
            user_id=ctx.user_id,
            name=data.name,
            email=email,
            is_archived=False,
        )
        self._session.add(friend)
        self._audit(ctx.user_id, "friend.created", friend.id, {"name": friend.name, "email": email},
                    request_id=request_id)  # fmt: skip
        invite = self._invite(ctx, friend, request_id) if email else None
        await self._commit()
        await self._session.refresh(friend)
        return self._view(friend, invite.status if invite else None)

    async def update(
        self,
        ctx: UserContext,
        friend_id: uuid.UUID,
        patch: FriendUpdate,
        *,
        request_id: str | None = None,
    ) -> FriendView:
        """Rename a friend and/or set, change or clear their email."""
        friend = await self._owned_friend(ctx.user_id, friend_id)
        changes: dict[str, list[Any]] = {}

        if patch.name is not None and patch.name != friend.name:
            changes["name"] = [friend.name, patch.name]
            friend.name = patch.name

        if "email" in patch.model_fields_set:
            email = _normalize_email(str(patch.email)) if patch.email else None
            if email != friend.email:
                if friend.linked_user_id is not None:
                    raise ConflictError(
                        "This friend is linked to a MoneyMoney account, so their email "
                        "cannot change.",
                        code="friend_linked",
                    )
                if email:
                    await self._ensure_email_is_usable(ctx, email, other_than=friend.id)
                # The old address is no longer invited; a new one gets a fresh invite.
                await self._session.execute(
                    update(FriendInvite)
                    .where(
                        FriendInvite.friend_id == friend.id,
                        FriendInvite.status.in_(("pending", "declined")),
                    )
                    .values(status="cancelled")
                )
                changes["email"] = [friend.email, email]
                friend.email = email
                if email:
                    self._invite(ctx, friend, request_id)

        if not changes:
            return await self._view_of(friend)
        self._audit(
            ctx.user_id, "friend.updated", friend.id, {"changes": changes}, request_id=request_id
        )
        await self._commit()
        await self._session.refresh(friend)
        return await self._view_of(friend)

    async def remove(
        self, ctx: UserContext, friend_id: uuid.UUID, *, request_id: str | None = None
    ) -> None:
        """Remove a friend: delete them, or archive them when they have shared history."""
        friend = await self._owned_friend(ctx.user_id, friend_id)
        details = {"name": friend.name, "email": friend.email, "linked": friend.linked_user_id is not None}  # fmt: skip
        if await self._has_shared_history(friend):
            friend.is_archived = True
            self._audit(ctx.user_id, "friend.archived", friend.id, details, request_id=request_id)
        else:
            await self._session.delete(friend)
            self._audit(ctx.user_id, "friend.removed", friend.id, details, request_id=request_id)
        await self._commit()

    async def _has_shared_history(self, friend: Friend) -> bool:
        """True when the friend is in a shared expense.

        Such a friend is archived instead of deleted, which keeps past expenses (and later
        balances and settlements) correct. Settlements will extend this check.
        """
        in_a_share = select(SharedExpenseShare.id).where(SharedExpenseShare.friend_id == friend.id)
        paid_one = select(SharedExpense.id).where(SharedExpense.payer_friend_id == friend.id)
        return (await self._session.scalar(in_a_share.limit(1))) is not None or (
            await self._session.scalar(paid_one.limit(1))
        ) is not None

    # -- invites --------------------------------------------------------------------------

    async def list_incoming_invites(self, ctx: UserContext) -> list[FriendInviteView]:
        """Pending invites sent to the signed-in user's email, oldest first."""
        rows = (
            await self._session.execute(
                self._incoming_invites(ctx).order_by(FriendInvite.created_at, FriendInvite.id)
            )
        ).all()
        return [
            FriendInviteView(
                id=invite.id,
                from_name=inviter.display_name,
                from_email=inviter.email,
                created_at=invite.created_at,
            )
            for invite, _, inviter in rows
        ]

    async def accept(
        self, ctx: UserContext, invite_id: uuid.UUID, *, request_id: str | None = None
    ) -> FriendView:
        """Accept an invite: link the inviter's friend row and the user's own row for them."""
        invite, inviters_row, inviter = await self._incoming_invite(ctx, invite_id)
        mine = await self._row_to_link(ctx, inviter, request_id)
        mine.linked_user_id = inviter.id
        inviters_row.linked_user_id = ctx.user_id
        # Any invite of mine to the inviter is now pointless: we are already linked.
        await self._session.execute(
            update(FriendInvite)
            .where(FriendInvite.friend_id == mine.id, FriendInvite.status == "pending")
            .values(status="cancelled")
        )
        invite.status = "accepted"
        invite.responded_at = func.now()
        self._audit(ctx.user_id, "friend_invite.accepted", invite.id, {"friend_id": str(mine.id)},
                    entity_type="friend_invite", request_id=request_id)  # fmt: skip
        self._audit(ctx.user_id, "friend.linked", mine.id, {"linked_user_id": str(inviter.id)},
                    request_id=request_id)  # fmt: skip
        # The inviter's row changed too, so it is recorded under the inviter.
        self._audit(inviter.id, "friend.linked", inviters_row.id,
                    {"linked_user_id": str(ctx.user_id)}, request_id=request_id)  # fmt: skip
        await self._commit()
        await self._session.refresh(mine)
        return self._view(mine, None)

    async def decline(
        self, ctx: UserContext, invite_id: uuid.UUID, *, request_id: str | None = None
    ) -> None:
        """Decline an invite. The inviter's friend stays unlinked, marked as declined."""
        invite, _, _ = await self._incoming_invite(ctx, invite_id)
        invite.status = "declined"
        invite.responded_at = func.now()
        self._audit(ctx.user_id, "friend_invite.declined", invite.id, None,
                    entity_type="friend_invite", request_id=request_id)  # fmt: skip
        await self._commit()

    # -- helpers --------------------------------------------------------------------------

    def _incoming_invites(self, ctx: UserContext) -> Any:
        # Matched by the user's email, so an invite sent before they signed up still finds them.
        my_email = select(User.email).where(User.id == ctx.user_id).scalar_subquery()
        return (
            select(FriendInvite, Friend, User)
            .join(Friend, Friend.id == FriendInvite.friend_id)
            .join(User, User.id == Friend.user_id)
            .where(FriendInvite.status == "pending", FriendInvite.invitee_email == my_email)
        )

    async def _incoming_invite(
        self, ctx: UserContext, invite_id: uuid.UUID
    ) -> tuple[FriendInvite, Friend, User]:
        row = (
            await self._session.execute(
                self._incoming_invites(ctx).where(FriendInvite.id == invite_id)
            )
        ).first()
        if row is None:  # someone else's, already answered, or never existed
            raise NotFoundError("Invite not found")
        invite, inviters_row, inviter = row
        return invite, inviters_row, inviter

    async def _row_to_link(self, ctx: UserContext, inviter: User, request_id: str | None) -> Friend:
        """The invited user's own friend row for the inviter: reuse one, or create it."""
        existing = await self._session.scalar(
            select(Friend)
            .where(
                Friend.user_id == ctx.user_id,
                Friend.is_archived.is_(False),
                (Friend.linked_user_id == inviter.id) | (Friend.email == inviter.email),
            )
            .order_by(Friend.created_at)
            .limit(1)
        )
        if existing is not None:
            return existing
        created = Friend(
            id=uuid7(),
            user_id=ctx.user_id,
            name=inviter.display_name,
            email=inviter.email,
            is_archived=False,
        )
        self._session.add(created)
        self._audit(ctx.user_id, "friend.created", created.id,
                    {"name": created.name, "email": created.email, "from_invite": True},
                    request_id=request_id)  # fmt: skip
        return created

    def _invite(self, ctx: UserContext, friend: Friend, request_id: str | None) -> FriendInvite:
        assert friend.email is not None
        invite = FriendInvite(
            id=uuid7(), friend_id=friend.id, invitee_email=friend.email, status="pending"
        )
        self._session.add(invite)
        self._audit(ctx.user_id, "friend_invite.sent", invite.id, {"friend_id": str(friend.id)},
                    entity_type="friend_invite", request_id=request_id)  # fmt: skip
        return invite

    async def _ensure_email_is_usable(
        self, ctx: UserContext, email: str, *, other_than: uuid.UUID | None = None
    ) -> None:
        own_email = await self._session.scalar(select(User.email).where(User.id == ctx.user_id))
        if email == own_email:
            raise ValidationFailedError(
                "You cannot add yourself as a friend.", details={"field": "email"}
            )
        query = select(Friend.id).where(
            Friend.user_id == ctx.user_id, Friend.is_archived.is_(False), Friend.email == email
        )
        if other_than is not None:
            query = query.where(Friend.id != other_than)
        if await self._session.scalar(query) is not None:
            raise _email_taken()

    async def _owned_friend(self, user_id: uuid.UUID, friend_id: uuid.UUID) -> Friend:
        # Ownership is part of the WHERE clause: another user's id is simply "not found".
        friend = await self._session.scalar(
            select(Friend).where(
                Friend.id == friend_id, Friend.user_id == user_id, Friend.is_archived.is_(False)
            )
        )
        if friend is None:
            raise NotFoundError("Friend not found")
        return friend

    async def _open_invite_statuses(self, friend_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
        """Friend id to "pending" or "declined", for friends whose invite is not settled."""
        if not friend_ids:
            return {}
        rows = await self._session.execute(
            select(FriendInvite.friend_id, FriendInvite.status).where(
                FriendInvite.friend_id.in_(friend_ids),
                FriendInvite.status.in_(("pending", "declined")),
            )
        )
        return {friend_id: status for friend_id, status in rows.all()}

    async def _view_of(self, friend: Friend) -> FriendView:
        statuses = await self._open_invite_statuses([friend.id])
        return self._view(friend, statuses.get(friend.id))

    @staticmethod
    def _view(friend: Friend, invite_status: str | None) -> FriendView:
        return FriendView(
            id=friend.id,
            name=friend.name,
            email=friend.email,
            is_linked=friend.linked_user_id is not None,
            invite_status=invite_status,
            created_at=friend.created_at,
            updated_at=friend.updated_at,
        )

    def _audit(
        self,
        user_id: uuid.UUID,
        action: str,
        entity_id: uuid.UUID,
        data: dict[str, Any] | None,
        *,
        entity_type: str = "friend",
        request_id: str | None,
    ) -> None:
        record_audit(
            self._session, user_id=user_id, actor="user", action=action,
            entity_type=entity_type, entity_id=entity_id, data=data, request_id=request_id,
        )  # fmt: skip

    async def _commit(self) -> None:
        # The unique index on active emails is the final word: two requests racing past the
        # check still cannot both save, and the loser gets the same 409.
        try:
            await self._session.commit()
        except IntegrityError as error:
            await self._session.rollback()
            if _violated_constraint(error) == ACTIVE_EMAIL_INDEX:
                raise _email_taken() from None
            raise
