"""One-time codes that prove the person accepting an invite owns the invited email.

Sign-up never verifies an email, so matching an invite by address alone would let anyone who
registers with someone else's address take their place. The code is emailed to that address,
so only its owner can read it. It follows the password-reset pattern:

- Only a hash is stored (of the invite id and the code), never the code.
- It expires after 15 minutes and works once; a newer code replaces the older one.
- Five wrong tries burn it, because six digits could otherwise be guessed one by one.
- One UPDATE both checks and claims it, so two requests cannot both use it.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.clock import Clock
from finance_core.email_sender import EmailMessage
from finance_core.friends.models import FriendInvite

CODE_LIFETIME = timedelta(minutes=15)
MAX_WRONG_TRIES = 5


def _hash_code(invite_id: uuid.UUID, code: str) -> bytes:
    # The invite id is mixed in so the same six digits hash differently for every invite.
    return hashlib.sha256(f"{invite_id}:{code}".encode()).digest()


class InviteCodes:
    """Issues and redeems the one-time code of a friend invite."""

    def __init__(self, session: AsyncSession, clock: Clock) -> None:
        self._session = session
        self._clock = clock

    def issue(self, invite: FriendInvite) -> str:
        """Make a new code for the invite, replacing any earlier one. The caller commits."""
        code = f"{secrets.randbelow(1_000_000):06d}"
        invite.code_hash = _hash_code(invite.id, code)
        invite.code_expires_at = self._clock.now() + CODE_LIFETIME
        invite.code_wrong_tries = 0
        return code

    async def redeem(self, invite_id: uuid.UUID, code: str) -> bool:
        """Use the code if it is right, unexpired and unspent; the caller commits.

        A wrong code is counted against the invite and is not redeemed. The count is saved by
        the caller too, so it must commit even when this returns False.
        """
        claimed = await self._session.scalar(
            update(FriendInvite)
            .where(
                FriendInvite.id == invite_id,
                FriendInvite.code_hash == _hash_code(invite_id, code),
                FriendInvite.code_expires_at > self._clock.now(),
                FriendInvite.code_wrong_tries < MAX_WRONG_TRIES,
            )
            .values(code_hash=None, code_expires_at=None)
            .returning(FriendInvite.id)
        )
        if claimed is not None:
            return True
        await self._session.execute(
            update(FriendInvite)
            .where(FriendInvite.id == invite_id)
            .values(code_wrong_tries=FriendInvite.code_wrong_tries + 1)
        )
        return False

    @staticmethod
    def email(address: str, code: str, *, inviter_name: str) -> EmailMessage:
        return EmailMessage(
            to=address,
            subject="Your MoneyMoney friend code",
            text=(
                f"Your code is {code}\n\n"
                f"{inviter_name} invited you to be friends on MoneyMoney. Enter this code "
                "to accept. It works once and expires in 15 minutes.\n"
                "If you didn't expect this, ignore this email: nothing changes."
            ),
        )
