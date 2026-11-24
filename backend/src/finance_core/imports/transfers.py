"""Suggest the other account and pair opposite sides of recorded transfers."""

from __future__ import annotations

import re
import uuid
from bisect import bisect_left
from collections import defaultdict, deque
from collections.abc import Sequence
from datetime import date
from hashlib import sha256

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.accounts.names import resolve_account_name
from finance_core.accounts.schemas import AccountView
from finance_core.imports.models import ImportRow, StatementTransferSide
from finance_core.transactions.models import Transaction

_MATCH_WINDOW_DAYS = 3
_CARD_PAYMENT = re.compile(r"\b(?:cc|(?:credit )?card) (?:bill )?(?:payment|pmt|autopay)\b")
_CARD_RECEIPT = re.compile(r"\b(?:payment (?:received|thank ?you|credited)|autopay payment)\b")
_SELF_TRANSFER = re.compile(r"\b(?:self|(?:transfer to )?own a ?c|own account)\b")
_WORDS = re.compile(r"[^\W_]+")
_SEGMENTS = re.compile(r"\s*(?:[/|:;]|\s[-\u2013\u2014]\s)\s*")
_HANDLES = re.compile(r"[\w.+-]+@[\w.-]+")


def _normalise(text: str) -> str:
    return " ".join(_WORDS.findall(text.casefold()))


def transfer_account_candidates(
    description: str | None,
    *,
    direction: str,
    account: AccountView,
    accounts: Sequence[AccountView],
) -> list[uuid.UUID]:
    """List active same-currency counterparts named or implied by the narration."""
    if not description:
        return []
    description = _HANDLES.sub(" ", description)
    narration = _normalise(description)
    if not narration:
        return []
    eligible = [
        other
        for other in accounts
        if other.id != account.id and other.currency == account.currency and not other.is_archived
    ]
    # Whole account names must be complete words, rather than part of an IFSC or handle.
    named = [
        other
        for other in eligible
        if (name := _normalise(other.name)) and f" {name} " in f" {narration} "
    ]
    if named:
        return [other.id for other in named]

    card_payment = _CARD_PAYMENT.search(narration) and "debit card" not in narration
    if account.kind == "credit_card" and direction == "in":
        if card_payment or _CARD_RECEIPT.search(narration):
            return [other.id for other in eligible if other.kind == "bank"]
    elif card_payment and direction == "out":
        return [other.id for other in eligible if other.kind == "credit_card"]
    if _SELF_TRANSFER.search(narration):
        return [other.id for other in eligible]

    # Phase 2 recognises a bank alias such as HDFC in a standalone counterparty segment.
    aliases = {
        other.id
        for part in _SEGMENTS.split(description)
        if (name := _normalise(part)) and any(char.isalpha() for char in name)
        if (other := resolve_account_name(name, eligible)) is not None
    }
    return [other.id for other in eligible if other.id in aliases]


async def lock_statement_transfers(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Serialize confirmations and undo across this user's separate statement imports."""
    key = sha256(b"statement transfers:" + user_id.bytes).digest()[:8]
    await session.execute(select(func.pg_advisory_xact_lock(int.from_bytes(key, signed=True))))


async def match_statement_transfers(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    currency: str,
    rows: Sequence[ImportRow],
    lock: bool = False,
) -> dict[uuid.UUID, uuid.UUID]:
    """Find at most one live transfer with a free side for each candidate row."""
    by_pair: dict[tuple[uuid.UUID, str, int], list[ImportRow]] = defaultdict(list)
    for row in rows:
        if (
            row.transfer_account_id is not None
            and row.amount_minor is not None
            and row.occurred_on is not None
            and row.direction is not None
        ):
            by_pair[row.transfer_account_id, row.direction, row.amount_minor].append(row)
    if not by_pair:
        return {}

    candidates = await _available_transfers(
        session, user_id=user_id, account_id=account_id, currency=currency,
        rows=rows, other_ids={other for other, _, _ in by_pair}, lock=lock,
    )  # fmt: skip
    result: dict[uuid.UUID, uuid.UUID] = {}
    for key, group in by_pair.items():
        available = deque(candidates[key])
        # Earliest admissible first leaves each later row the most remaining choices.
        for row in sorted(group, key=lambda item: (str(item.occurred_on), item.position)):
            assert row.occurred_on is not None
            ordinal = row.occurred_on.toordinal()
            while available and available[0].occurred_on.toordinal() < ordinal - _MATCH_WINDOW_DAYS:
                available.popleft()
            if available and available[0].occurred_on.toordinal() <= ordinal + _MATCH_WINDOW_DAYS:
                result[row.id] = available.popleft().id
    return result


async def infer_transfer_accounts(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    currency: str,
    ambiguous: list[tuple[ImportRow, list[uuid.UUID]]],
) -> dict[uuid.UUID, uuid.UUID]:
    """Resolve a generic transfer narration only if exactly one account has a match."""
    if not ambiguous:
        return {}
    candidates = await _available_transfers(
        session, user_id=user_id, account_id=account_id, currency=currency,
        rows=[row for row, _ in ambiguous],
        other_ids={other for _, accounts in ambiguous for other in accounts},
    )  # fmt: skip
    found: dict[uuid.UUID, uuid.UUID] = {}
    for row, targets in ambiguous:
        assert (
            row.occurred_on is not None
            and row.amount_minor is not None
            and row.direction is not None
        )
        day = row.occurred_on.toordinal()
        likely = []
        for target in targets:
            transfers = candidates[target, row.direction, row.amount_minor]
            index = bisect_left(
                transfers, day - _MATCH_WINDOW_DAYS, key=lambda t: t.occurred_on.toordinal()
            )
            if (
                index < len(transfers)
                and transfers[index].occurred_on.toordinal() <= day + _MATCH_WINDOW_DAYS
            ):
                likely.append(target)
        if len(likely) == 1:
            found[row.id] = likely[0]
    return found


async def _available_transfers(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    currency: str,
    rows: Sequence[ImportRow],
    other_ids: set[uuid.UUID],
    lock: bool = False,
) -> defaultdict[tuple[uuid.UUID, str, int], list[Transaction]]:
    dates = [row.occurred_on.toordinal() for row in rows if row.occurred_on is not None]
    earliest = date.fromordinal(max(date.min.toordinal(), min(dates) - _MATCH_WINDOW_DAYS))
    latest = date.fromordinal(min(date.max.toordinal(), max(dates) + _MATCH_WINDOW_DAYS))
    claimed = select(StatementTransferSide.transfer_id).where(
        StatementTransferSide.transfer_id == Transaction.id,
        StatementTransferSide.account_id == account_id,
        StatementTransferSide.user_id == user_id,
    )
    query = (
        select(Transaction)
        .where(
            Transaction.user_id == user_id,
            Transaction.type == "transfer",
            Transaction.deleted_at.is_(None),
            Transaction.currency == currency,
            Transaction.amount_minor.in_(
                {row.amount_minor for row in rows if row.amount_minor is not None}
            ),
            Transaction.occurred_on.between(earliest, latest),
            or_(
                (Transaction.account_id == account_id) & Transaction.to_account_id.in_(other_ids),
                (Transaction.to_account_id == account_id) & Transaction.account_id.in_(other_ids),
            ),
            ~claimed.exists(),
        )
        .order_by(Transaction.occurred_on, Transaction.id)
    )
    if lock:
        query = query.with_for_update()
    candidates: defaultdict[tuple[uuid.UUID, str, int], list[Transaction]] = defaultdict(list)
    for transfer in await session.scalars(query):
        if transfer.account_id == account_id:
            other, direction = transfer.to_account_id, "out"
        else:
            other, direction = transfer.account_id, "in"
        assert other is not None
        candidates[other, direction, transfer.amount_minor].append(transfer)

    return candidates
