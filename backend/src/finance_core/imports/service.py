"""Import service: preview a statement, let the user adjust it, save it, undo it.

Flow: `start` reads the file and stores a preview (the file itself is never kept); the user
confirms the statement layout once per account (`save_layout`), ticks and recategorises rows
(`update_rows`); `confirm` saves the ticked rows as transactions in one database transaction;
`undo` removes them again. Everything is scoped by user, and another user's import is a 404.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from finance_core.accounts.models import Account
from finance_core.accounts.schemas import AccountRef
from finance_core.accounts.service import AccountService
from finance_core.audit.service import record_audit
from finance_core.cache.primitives import UserDataGeneration
from finance_core.categories.models import Category
from finance_core.categories.schemas import CategoryRef
from finance_core.categories.service import CategoryService
from finance_core.clock import Clock
from finance_core.errors import ConflictError, NotFoundError, ValidationFailedError
from finance_core.ids import uuid7
from finance_core.imports.categorise import CategoryPicker
from finance_core.imports.cells import cell_text, guess_date_order
from finance_core.imports.columns import guess_columns, header_signature
from finance_core.imports.fingerprint import assign_fingerprints
from finance_core.imports.merchant import extract_merchant
from finance_core.imports.models import ImportRow, StatementImport, StatementLayout
from finance_core.imports.readers import read_csv
from finance_core.imports.rows import ParsedRow, parse_data_rows
from finance_core.imports.schemas import (
    ColumnMap,
    ColumnMapInput,
    ImportDetail,
    ImportSummary,
    PreviewCounts,
    PreviewRow,
    RowChanges,
    RowStatusField,
)
from finance_core.imports.table import check_file_size, locate_table
from finance_core.merchants.service import MerchantRuleService
from finance_core.money import format_money, from_minor
from finance_core.transactions.models import Transaction
from finance_core.transactions.schemas import NewTransaction
from finance_core.transactions.service import TransactionService
from finance_core.users.context import UserContext

PREVIEW_LIFETIME = timedelta(hours=24)
SAMPLE_ROWS = 5
DEFAULT_PAGE_SIZE = 200
MAX_PAGE_SIZE = 500
MAX_DESCRIPTION = 500
SAVEABLE_STATUSES = ("to_import", "likely_duplicate", "transfer")


def _not_previewing() -> ConflictError:
    return ConflictError(
        "This import has already been saved or removed.", code="import_not_previewing"
    )


def _type_of(direction: str | None) -> str | None:
    return {"out": "expense", "in": "income"}.get(direction or "")


class ImportService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock,
        generation: UserDataGeneration | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._accounts = AccountService(session)
        self._categories = CategoryService(session)
        self._transactions = TransactionService(session, clock=clock, generation=generation)
        self._rules = MerchantRuleService(session, clock=clock)

    # -- starting an import -----------------------------------------------------------------

    async def start(
        self,
        ctx: UserContext,
        *,
        account_id: uuid.UUID,
        file_name: str,
        data: bytes,
        request_id: str | None = None,
    ) -> ImportDetail:
        """Read a CSV statement into a preview. Nothing is saved as a transaction yet."""
        account = await self._accounts.pick_for_transaction(ctx, account_id, field="accountId")
        check_file_size(data)
        table = locate_table(read_csv(data))
        await self.purge_expired(ctx.user_id)

        columns = guess_columns(table.headers)
        if columns.date_column is not None:
            columns.date_order = guess_date_order(
                [
                    row[columns.date_column]
                    for row in table.data_rows
                    if columns.date_column < len(row)
                ]
            )
        signature = header_signature(table.headers)
        saved = await self._saved_layout(ctx.user_id, account_id)
        layout_confirmed = saved is not None and saved.header_signature == signature
        if layout_confirmed:
            assert saved is not None
            columns = _columns_of(saved)

        now = self._clock.now()
        imp = StatementImport(
            id=uuid7(),
            user_id=ctx.user_id,
            account_id=account.id,
            file_name=file_name[:255],
            status="previewing",
            currency=account.currency,
            header_cells=[cell_text(cell) for cell in table.headers],
            header_signature=signature,
            layout=columns.model_dump(),
            layout_confirmed=layout_confirmed,
            row_count=len(table.data_rows),
            expires_at=now + PREVIEW_LIFETIME,
        )
        self._session.add(imp)
        await self._session.flush()
        raw_rows = [[cell_text(cell) for cell in row] for row in table.data_rows]
        await self._rebuild_rows(ctx, imp, columns, raw_rows)
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="import.started",
            entity_type="statement_import", entity_id=imp.id,
            data={"accountId": str(account.id), "fileName": imp.file_name,
                  "rowCount": imp.row_count},
            request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        return await self._detail(ctx, imp)

    # -- reading ----------------------------------------------------------------------------

    async def get(
        self,
        ctx: UserContext,
        import_id: uuid.UUID,
        *,
        status: RowStatusField | None = None,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ImportDetail:
        imp = await self._own_import(ctx.user_id, import_id)
        return await self._detail(ctx, imp, status=status, offset=offset, limit=limit)

    async def list_imports(self, ctx: UserContext) -> list[ImportSummary]:
        await self.purge_expired(ctx.user_id)
        rows = (
            await self._session.execute(
                select(StatementImport, Account)
                .join(Account, Account.id == StatementImport.account_id)
                .where(StatementImport.user_id == ctx.user_id)
                .order_by(StatementImport.created_at.desc(), StatementImport.id.desc())
                .limit(100)
            )
        ).all()
        return [_summary(imp, account) for imp, account in rows]

    # -- adjusting the preview --------------------------------------------------------------

    async def save_layout(
        self,
        ctx: UserContext,
        import_id: uuid.UUID,
        columns: ColumnMapInput,
        *,
        request_id: str | None = None,
    ) -> ImportDetail:
        """Confirm (or correct) the layout, remember it for the account, and re-read the rows."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "previewing":
            raise _not_previewing()
        layout = ColumnMap.model_validate(columns.model_dump())
        if not layout.is_usable():
            raise ValidationFailedError(
                "Pick the date column and the amount column, or both the debit and credit columns.",
                details={"field": "layout"},
            )
        if any(column >= len(imp.header_cells) for column in layout.used_columns()):
            raise ValidationFailedError(
                "A chosen column is not in the file.", details={"field": "layout"}
            )
        assert layout.date_column is not None  # is_usable() checked it
        await self._remember_layout(ctx.user_id, imp, layout)
        imp.layout = layout.model_dump()
        imp.layout_confirmed = True
        raw_rows = list(
            await self._session.scalars(
                select(ImportRow.raw_cells)
                .where(ImportRow.import_id == imp.id, ImportRow.user_id == ctx.user_id)
                .order_by(ImportRow.position)
            )
        )
        await self._rebuild_rows(ctx, imp, layout, raw_rows)
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="statement_layout.saved",
            entity_type="statement_import", entity_id=imp.id,
            data={"accountId": str(imp.account_id), "layout": imp.layout}, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        return await self._detail(ctx, imp)

    async def update_rows(
        self,
        ctx: UserContext,
        import_id: uuid.UUID,
        changes: RowChanges,
        *,
        request_id: str | None = None,
    ) -> ImportDetail:
        """Tick, untick or recategorise preview rows. A category the user picks is remembered
        as theirs, so only those rows teach merchant rules when the import is saved."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "previewing":
            raise _not_previewing()
        wanted = {change.id for change in changes.rows}
        rows = {
            row.id: row
            for row in await self._session.scalars(
                select(ImportRow).where(
                    ImportRow.id.in_(wanted),
                    ImportRow.import_id == imp.id,
                    ImportRow.user_id == ctx.user_id,
                )
            )
        }
        if wanted - rows.keys():
            raise NotFoundError("Import row not found")
        for change in changes.rows:
            row = rows[change.id]
            if change.is_selected is not None:
                self._tick(row, change.is_selected)
            if change.category_id is not None:
                await self._set_category(ctx, row, change.category_id)
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="import.rows_changed",
            entity_type="statement_import", entity_id=imp.id,
            data={"rowsChanged": len(changes.rows)}, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        return await self._detail(ctx, imp)

    def _tick(self, row: ImportRow, selected: bool) -> None:
        if selected and (row.status == "skipped" or row.occurred_on is None):
            raise ValidationFailedError(
                f"Row {row.position} can't be imported: {row.note or 'it was skipped'}.",
                details={"field": "isSelected"},
            )
        row.is_selected = selected

    async def _set_category(self, ctx: UserContext, row: ImportRow, category_id: uuid.UUID) -> None:
        row_type = _type_of(row.direction)
        if row_type is None:
            raise ValidationFailedError(
                f"Row {row.position} can't be imported, so it has no category.",
                details={"field": "categoryId"},
            )
        category = await self._categories.get_visible(ctx.user_id, category_id)
        if category.kind != row_type:
            raise ValidationFailedError(
                f"'{category.name}' is an {category.kind} category.",
                details={"field": "categoryId"},
            )
        row.category_id = category.id
        row.category_source = "user"

    # -- saving and undoing -----------------------------------------------------------------

    async def confirm(
        self, ctx: UserContext, import_id: uuid.UUID, *, request_id: str | None = None
    ) -> ImportDetail:
        """Save every ticked row as a transaction, all in one database transaction."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "previewing":
            raise _not_previewing()
        if not imp.layout_confirmed:
            raise ConflictError(
                "Confirm which columns are the date, description and amount first.",
                code="layout_not_confirmed",
            )
        account = await self._accounts.pick_for_transaction(ctx, imp.account_id, field="accountId")
        rows = (
            await self._session.scalars(
                select(ImportRow)
                .where(
                    ImportRow.import_id == imp.id,
                    ImportRow.user_id == ctx.user_id,
                    ImportRow.is_selected.is_(True),
                    ImportRow.status.in_(SAVEABLE_STATUSES),
                )
                .order_by(ImportRow.position)
            )
        ).all()
        # Only a category the user chose in the preview teaches a merchant rule.
        chosen = [row for row in rows if row.category_source == "user"]
        guessed = [row for row in rows if row.category_source != "user"]
        created = 0
        for group, learns in ((chosen, True), (guessed, False)):
            items = [
                (_new_transaction(row, account.id, imp.currency), row.fingerprint or "")
                for row in group
            ]
            created += await self._transactions.create_imported(
                ctx, items, source_ref=str(imp.id), learn_merchants=learns, request_id=request_id
            )

        imp.status = "imported"
        imp.imported_count = created
        imp.skipped_count = imp.row_count - created
        imp.confirmed_at = self._clock.now()
        imp.expires_at = None
        # The raw cells (references, balances) are not needed once the rows are saved.
        await self._session.execute(
            update(ImportRow).where(ImportRow.import_id == imp.id).values(raw_cells=[])
        )
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="import.confirmed",
            entity_type="statement_import", entity_id=imp.id,
            data={"accountId": str(imp.account_id), "imported": created, "rowCount": imp.row_count},
            request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        await self._transactions.bump_pending_generations()
        return await self._detail(ctx, imp)

    async def undo(
        self, ctx: UserContext, import_id: uuid.UUID, *, request_id: str | None = None
    ) -> ImportDetail:
        """Soft-delete everything this import created and free its fingerprints for a re-import."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "imported":
            raise ConflictError("Only a saved import can be undone.", code="import_not_imported")
        mine = (
            Transaction.user_id == ctx.user_id,
            Transaction.source == "import",
            Transaction.source_ref == str(imp.id),
        )
        live_ids = list(
            await self._session.scalars(
                select(Transaction.id).where(*mine, Transaction.deleted_at.is_(None))
            )
        )
        # Clearing the idempotency key on every row of the import (also ones the user deleted
        # by hand) is what lets the same file be imported again.
        await self._session.execute(
            update(Transaction)
            .where(*mine)
            .values(
                deleted_at=func.coalesce(Transaction.deleted_at, self._clock.now()),
                idempotency_key=None,
                version=Transaction.version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        for transaction_id in live_ids:
            record_audit(
                self._session, user_id=ctx.user_id, actor="user", action="transaction.deleted",
                entity_type="transaction", entity_id=transaction_id,
                data={"importId": str(imp.id), "reason": "import_undone"}, request_id=request_id,
            )  # fmt: skip
        imp.status = "undone"
        imp.undone_at = self._clock.now()
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="import.undone",
            entity_type="statement_import", entity_id=imp.id,
            data={"removed": len(live_ids)}, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        await self._transactions.bump_generation(ctx.user_id)
        return await self._detail(ctx, imp)

    async def discard(
        self, ctx: UserContext, import_id: uuid.UUID, *, request_id: str | None = None
    ) -> None:
        """Throw away a preview that was never saved."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "previewing":
            raise _not_previewing()
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="import.discarded",
            entity_type="statement_import", entity_id=imp.id, request_id=request_id,
        )  # fmt: skip
        await self._session.delete(imp)  # the database removes its rows
        await self._session.commit()

    async def purge_expired(self, user_id: uuid.UUID | None = None) -> int:
        """Delete unconfirmed previews older than 24 hours (for one user, or for everyone)."""
        expired = delete(StatementImport).where(
            StatementImport.status == "previewing",
            StatementImport.expires_at <= self._clock.now(),
        )
        if user_id is not None:
            expired = expired.where(StatementImport.user_id == user_id)
        gone = (
            await self._session.execute(
                expired.returning(StatementImport.id, StatementImport.user_id)
            )
        ).all()
        for import_id, owner_id in gone:
            record_audit(
                self._session, user_id=owner_id, actor="system", action="import.expired",
                entity_type="statement_import", entity_id=import_id,
            )  # fmt: skip
        await self._session.commit()
        return len(gone)

    # -- building the preview ---------------------------------------------------------------

    async def _rebuild_rows(
        self, ctx: UserContext, imp: StatementImport, columns: ColumnMap, raw_rows: list[list[str]]
    ) -> None:
        """(Re)build the preview rows from the stored cells under a layout."""
        parsed = parse_data_rows(
            raw_rows, columns, currency=imp.currency, today=ctx.today(self._clock)
        )
        fingerprints = assign_fingerprints(imp.account_id, parsed)
        already_saved = await self._saved_keys(ctx.user_id, [f for f in fingerprints if f])
        picker = await CategoryPicker.for_user(
            ctx.user_id, categories=self._categories, rules=self._rules
        )
        # Merchants are read once per row, then every rule is fetched in one query.
        merchants = [extract_merchant(row.description) for row in parsed]
        await picker.prepare(
            [
                (_type_of(row.direction) or "", merchant)
                for row, merchant in zip(parsed, merchants, strict=True)
            ]
        )
        # Later steps (likely duplicates, transfers) add their own statuses on top of this one.
        built = [
            self._preview_row(ctx, imp, picker, row, merchant, fingerprint, already_saved)
            for row, merchant, fingerprint in zip(parsed, merchants, fingerprints, strict=True)
        ]
        await self._session.execute(delete(ImportRow).where(ImportRow.import_id == imp.id))
        if built:
            await self._session.execute(insert(ImportRow), built)
        imp.row_count = len(built)

    def _preview_row(
        self,
        ctx: UserContext,
        imp: StatementImport,
        picker: CategoryPicker,
        row: ParsedRow,
        merchant: str | None,
        fingerprint: str | None,
        already_saved: set[str],
    ) -> dict[str, Any]:
        description = (row.description or "")[:MAX_DESCRIPTION] or None
        values: dict[str, Any] = {
            "id": uuid7(), "import_id": imp.id, "user_id": ctx.user_id,
            "position": row.position, "raw_cells": row.raw_cells,
            "occurred_on": row.occurred_on, "amount_minor": row.amount_minor,
            "direction": row.direction, "description": description,
            "merchant": None, "category_id": None, "category_source": None,
            "status": "skipped", "note": row.problem, "is_selected": False,
            "fingerprint": fingerprint,
        }  # fmt: skip
        if row.problem is not None:
            return values
        if fingerprint in already_saved:
            return {**values, "note": "Already imported"}
        row_type = _type_of(row.direction)
        assert row_type is not None
        choice = picker.pick(row_type=row_type, merchant=merchant)
        return {
            **values, "merchant": merchant, "category_id": choice.category_id,
            "category_source": choice.source, "status": "to_import", "note": None,
            "is_selected": True,
        }  # fmt: skip

    async def _saved_keys(self, user_id: uuid.UUID, fingerprints: list[str]) -> set[str]:
        """Fingerprints that already belong to a transaction (live, or deleted by hand)."""
        if not fingerprints:
            return set()
        found = await self._session.scalars(
            select(Transaction.idempotency_key).where(
                Transaction.user_id == user_id, Transaction.idempotency_key.in_(fingerprints)
            )
        )
        return {key for key in found if key}

    # -- layouts ----------------------------------------------------------------------------

    async def _saved_layout(
        self, user_id: uuid.UUID, account_id: uuid.UUID
    ) -> StatementLayout | None:
        return await self._session.scalar(
            select(StatementLayout).where(
                StatementLayout.user_id == user_id, StatementLayout.account_id == account_id
            )
        )

    async def _remember_layout(
        self, user_id: uuid.UUID, imp: StatementImport, layout: ColumnMap
    ) -> None:
        saved = await self._saved_layout(user_id, imp.account_id)
        if saved is None:
            saved = StatementLayout(id=uuid7(), user_id=user_id, account_id=imp.account_id)
            self._session.add(saved)
        saved.header_signature = imp.header_signature
        assert layout.date_column is not None
        saved.date_column = layout.date_column
        saved.description_column = layout.description_column
        saved.amount_column = layout.amount_column
        saved.debit_column = layout.debit_column
        saved.credit_column = layout.credit_column
        saved.reference_column = layout.reference_column
        saved.date_order = layout.date_order

    # -- views ------------------------------------------------------------------------------

    async def _own_import(
        self, user_id: uuid.UUID, import_id: uuid.UUID, *, lock: bool = False
    ) -> StatementImport:
        # Ownership is part of the WHERE clause: another user's import is simply "not found".
        query = select(StatementImport).where(
            StatementImport.id == import_id, StatementImport.user_id == user_id
        )
        if lock:
            query = query.with_for_update()  # a double-clicked confirm waits for the first
        imp = await self._session.scalar(query)
        expired = (
            imp is not None
            and imp.status == "previewing"
            and imp.expires_at is not None
            and imp.expires_at <= self._clock.now()
        )
        if imp is None or expired:
            raise NotFoundError("Import not found")
        return imp

    async def _detail(
        self,
        ctx: UserContext,
        imp: StatementImport,
        *,
        status: RowStatusField | None = None,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> ImportDetail:
        account = await self._session.get(Account, imp.account_id)
        assert account is not None
        page = (
            select(ImportRow, Category)
            .outerjoin(Category, Category.id == ImportRow.category_id)
            .where(ImportRow.import_id == imp.id, ImportRow.user_id == ctx.user_id)
        )
        if status is not None:
            page = page.where(ImportRow.status == status)
        total = await self._session.scalar(select(func.count()).select_from(page.subquery()))
        rows = (
            await self._session.execute(
                page.order_by(ImportRow.position)
                .offset(max(offset, 0))
                .limit(max(1, min(limit, MAX_PAGE_SIZE)))
            )
        ).all()
        sample_rows = list(
            await self._session.scalars(
                select(ImportRow.raw_cells)
                .where(ImportRow.import_id == imp.id, ImportRow.user_id == ctx.user_id)
                .order_by(ImportRow.position)
                .limit(SAMPLE_ROWS)
            )
        )
        return ImportDetail(
            **_summary(imp, account).model_dump(),
            headers=imp.header_cells,
            sample_rows=sample_rows,
            layout=ColumnMap.model_validate(imp.layout),
            layout_confirmed=imp.layout_confirmed,
            counts=await self._counts(imp),
            rows=[
                _preview_row_view(row, category, imp.currency, ctx.locale) for row, category in rows
            ],
            rows_total=total or 0,
        )

    async def _counts(self, imp: StatementImport) -> PreviewCounts:
        """Row counts and ticked totals, summed by the database."""
        grouped = (
            await self._session.execute(
                select(
                    ImportRow.status,
                    ImportRow.is_selected,
                    ImportRow.direction,
                    func.count(),
                    func.coalesce(func.sum(ImportRow.amount_minor), 0),
                )
                .where(ImportRow.import_id == imp.id)
                .group_by(ImportRow.status, ImportRow.is_selected, ImportRow.direction)
            )
        ).all()
        by_status: dict[str, int] = defaultdict(int)
        selected = selected_out = selected_in = 0
        for status, is_selected, direction, count, amount in grouped:
            by_status[status] += count
            if is_selected:
                selected += count
                if direction == "out":
                    selected_out += int(amount or 0)
                elif direction == "in":
                    selected_in += int(amount or 0)
        return PreviewCounts(
            to_import=by_status["to_import"],
            skipped=by_status["skipped"],
            likely_duplicates=by_status["likely_duplicate"],
            transfers=by_status["transfer"],
            selected=selected,
            selected_out_minor=selected_out,
            selected_in_minor=selected_in,
        )


def _columns_of(saved: StatementLayout) -> ColumnMap:
    return ColumnMap(
        date_column=saved.date_column,
        description_column=saved.description_column,
        amount_column=saved.amount_column,
        debit_column=saved.debit_column,
        credit_column=saved.credit_column,
        reference_column=saved.reference_column,
        date_order=saved.date_order,
    )


def _summary(imp: StatementImport, account: Account) -> ImportSummary:
    return ImportSummary(
        id=imp.id,
        account=AccountRef(id=account.id, name=account.name, kind=account.kind),
        file_name=imp.file_name,
        status=imp.status,
        currency=imp.currency,
        row_count=imp.row_count,
        imported_count=imp.imported_count,
        skipped_count=imp.skipped_count,
        created_at=imp.created_at,
        expires_at=imp.expires_at,
        confirmed_at=imp.confirmed_at,
        undone_at=imp.undone_at,
    )


def _preview_row_view(
    row: ImportRow, category: Category | None, currency: str, locale: str
) -> PreviewRow:
    return PreviewRow(
        id=row.id,
        position=row.position,
        occurred_on=row.occurred_on,
        direction=row.direction,
        amount=from_minor(row.amount_minor, currency) if row.amount_minor is not None else None,
        amount_minor=row.amount_minor,
        amount_formatted=(
            format_money(row.amount_minor, currency, locale)
            if row.amount_minor is not None
            else None
        ),
        description=row.description,
        merchant=row.merchant,
        category=(
            CategoryRef(id=category.id, slug=category.slug, name=category.name, icon=category.icon)
            if category
            else None
        ),
        category_source=row.category_source,
        status=row.status,
        note=row.note,
        is_selected=row.is_selected,
    )


def _new_transaction(row: ImportRow, account_id: uuid.UUID, currency: str) -> NewTransaction:
    row_type = _type_of(row.direction)
    assert row_type is not None and row.amount_minor is not None and row.occurred_on is not None
    return NewTransaction(
        type=row_type,
        amount_minor=row.amount_minor,
        currency=currency,
        occurred_on=row.occurred_on,
        category_id=row.category_id,
        description=row.description,
        merchant=row.merchant,
        payment_method=None,
        account_id=account_id,
    )
