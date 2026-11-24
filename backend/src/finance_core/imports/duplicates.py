"""Match statement rows to existing transactions, one row per transaction."""

from sqlalchemy import ColumnElement, and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.imports.models import ImportRow, StatementImport, StatementTransferSide
from finance_core.transactions.models import Transaction


def _transaction_direction(imp: StatementImport) -> ColumnElement[str]:
    return case(
        (or_(Transaction.type == "income", Transaction.to_account_id == imp.account_id), "in"),
        else_="out",
    )


def current_duplicate_match(imp: StatementImport) -> ColumnElement[bool]:
    """Check whether a previously matched transaction still fits its preview row."""
    return and_(
        Transaction.id == ImportRow.matched_transaction_id,
        Transaction.user_id == imp.user_id,
        or_(Transaction.account_id == imp.account_id, Transaction.to_account_id == imp.account_id),
        Transaction.deleted_at.is_(None),
        Transaction.currency == imp.currency,
        Transaction.occurred_on == ImportRow.occurred_on,
        Transaction.amount_minor == ImportRow.amount_minor,
        _transaction_direction(imp) == ImportRow.direction,
    )


async def clear_stale_likely_duplicates(session: AsyncSession, imp: StatementImport) -> int:
    """Clear duplicate flags whose ledger match changed since the user reviewed the statement."""
    flagged = (
        ImportRow.import_id == imp.id,
        ImportRow.user_id == imp.user_id,
        ImportRow.status == "likely_duplicate",
    )
    live = await session.scalars(
        select(ImportRow.id)
        .join(Transaction, current_duplicate_match(imp))
        .where(*flagged)
        .order_by(Transaction.id)
        .with_for_update(read=True, of=Transaction)
    )
    changed = await session.scalars(
        update(ImportRow)
        .where(*flagged, ImportRow.id.not_in(live.all()))
        .values(
            status="to_import",
            matched_transaction_id=None,
            note="The earlier match changed. Review whether to include this row.",
        )
        .returning(ImportRow.id)
    )
    return len(changed.all())


async def mark_likely_duplicates(session: AsyncSession, imp: StatementImport) -> None:
    """Flag and untick rows that match live transactions in the import's account."""
    in_import = (ImportRow.import_id == imp.id, ImportRow.user_id == imp.user_id)
    # Pair the first eligible row with the first transaction of the same date, amount
    # and direction, then the second with the second, so no transaction is used twice.
    rows = (
        select(
            ImportRow.id,
            ImportRow.occurred_on,
            ImportRow.amount_minor,
            ImportRow.direction,
            func.row_number()
            .over(
                partition_by=(ImportRow.occurred_on, ImportRow.amount_minor, ImportRow.direction),
                order_by=ImportRow.position,
            )
            .label("occurrence"),
        )
        .where(*in_import, ImportRow.status == "to_import")
        .cte("eligible_statement_rows")
    )
    keys = select(rows.c.occurred_on, rows.c.amount_minor, rows.c.direction).distinct().subquery()
    already_imported = (
        select(ImportRow.id)
        .where(*in_import, ImportRow.fingerprint == Transaction.idempotency_key)
        .exists()
    )
    already_linked = (
        select(StatementTransferSide.transfer_id)
        .join(ImportRow, ImportRow.fingerprint == StatementTransferSide.fingerprint)
        .where(
            *in_import,
            StatementTransferSide.user_id == imp.user_id,
            StatementTransferSide.account_id == imp.account_id,
            StatementTransferSide.transfer_id == Transaction.id,
        )
        .exists()
    )
    # A transfer is outgoing from its source account and incoming to its destination account.
    direction = _transaction_direction(imp)
    matches = (
        select(
            Transaction.id,
            Transaction.occurred_on,
            Transaction.amount_minor,
            direction.label("direction"),
            func.row_number()
            .over(
                partition_by=(Transaction.occurred_on, Transaction.amount_minor, direction),
                order_by=Transaction.id,
            )
            .label("occurrence"),
        )
        .join(
            keys,
            (Transaction.occurred_on == keys.c.occurred_on)
            & (Transaction.amount_minor == keys.c.amount_minor)
            & (direction == keys.c.direction),
        )
        .where(
            Transaction.user_id == imp.user_id,
            or_(
                Transaction.account_id == imp.account_id,
                Transaction.to_account_id == imp.account_id,
            ),
            Transaction.currency == imp.currency,
            Transaction.deleted_at.is_(None),
            ~already_imported,
            ~already_linked,
        )
        .subquery()
    )
    await session.execute(
        update(ImportRow)
        .where(
            *in_import,
            ImportRow.id == rows.c.id,
            rows.c.occurred_on == matches.c.occurred_on,
            rows.c.amount_minor == matches.c.amount_minor,
            rows.c.direction == matches.c.direction,
            rows.c.occurrence == matches.c.occurrence,
        )
        .values(status="likely_duplicate", is_selected=False, matched_transaction_id=matches.c.id)
        .execution_options(synchronize_session=False)
    )
