"""Import service: preview a statement, let the user adjust it, save it, undo it.

Flow: `start` reads the file and stores a preview (the file itself is never kept); the user
confirms the statement layout once per account (`save_layout`), ticks and recategorises rows
(`update_rows`); `confirm` saves the ticked rows as transactions in one database transaction;
`undo` removes them again. Everything is scoped by user, and another user's import is a 404.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from datetime import timedelta
from hashlib import sha256
from pathlib import PurePath
from typing import Any

from sqlalchemy import delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from finance_core.accounts.models import Account
from finance_core.accounts.schemas import AccountRef, AccountView
from finance_core.accounts.service import AccountService
from finance_core.audit.service import record_audit
from finance_core.cache.primitives import UserDataGeneration
from finance_core.categories.defaults import CategoryKind
from finance_core.categories.models import Category
from finance_core.categories.schemas import CategoryRef
from finance_core.categories.service import CategoryService
from finance_core.clock import Clock
from finance_core.errors import ConflictError, NotFoundError, ValidationFailedError
from finance_core.ids import uuid7
from finance_core.imports.categorise import (
    CategoryChoice,
    StatementCategorizer,
    StatementCategoryRow,
    category_text,
    pick_categories,
)
from finance_core.imports.cells import cell_text, guess_date_order
from finance_core.imports.columns import guess_columns, header_signature
from finance_core.imports.duplicates import (
    clear_stale_likely_duplicates,
    current_duplicate_match,
    mark_likely_duplicates,
)
from finance_core.imports.fingerprint import assign_fingerprints
from finance_core.imports.merchant import extract_merchant
from finance_core.imports.models import (
    ImportRow,
    StatementImport,
    StatementLayout,
    StatementTransferSide,
)
from finance_core.imports.readers import read_csv
from finance_core.imports.rows import ParsedRow, parse_data_rows
from finance_core.imports.schemas import (
    ColumnMap,
    ColumnMapInput,
    ImportDetail,
    ImportSummary,
    MatchedTransaction,
    PreviewCounts,
    PreviewRow,
    RowChanges,
    RowStatusField,
)
from finance_core.imports.table import StatementTable, check_file_size, locate_table
from finance_core.imports.transfers import (
    infer_transfer_accounts,
    lock_statement_transfers,
    match_statement_transfers,
    transfer_account_candidates,
)
from finance_core.imports.workbook import read_workbook
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
_KINDS_BY_DIRECTION: dict[str, CategoryKind] = {"out": "expense", "in": "income"}


def _not_previewing() -> ConflictError:
    return ConflictError(
        "This import has already been saved or removed.", code="import_not_previewing"
    )


def _check_preview_revision(imp: StatementImport, expected: int | None) -> None:
    # Existing single-table clients can omit the version. Switching worksheets always requires it.
    if expected is None and len(imp.sheet_names or []) <= 1:
        return
    if expected != imp.preview_revision:
        raise ConflictError(
            "This preview changed. Review the latest rows and try again.", code="stale_preview"
        )


def _type_of(direction: str | None) -> CategoryKind | None:
    return _KINDS_BY_DIRECTION.get(direction or "")


class ImportService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock,
        generation: UserDataGeneration | None = None,
        categorizer: StatementCategorizer | None = None,
    ) -> None:
        self._session = session
        self._clock = clock
        self._accounts = AccountService(session)
        self._categories = CategoryService(session)
        self._transactions = TransactionService(session, clock=clock, generation=generation)
        self._rules = MerchantRuleService(session, clock=clock)
        self._categorizer = categorizer

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
        """Read a CSV or Excel statement into a preview before saving any transactions."""
        account = await self._accounts.pick_for_transaction(ctx, account_id, field="accountId")
        check_file_size(data)
        saved = await self._saved_layout(ctx.user_id, account_id)
        imp = StatementImport(
            id=uuid7(),
            user_id=ctx.user_id,
            account_id=account.id,
            file_name=file_name[:255],
            status="previewing",
            currency=account.currency,
            expires_at=self._clock.now() + PREVIEW_LIFETIME,
        )
        suffix = PurePath(file_name).suffix.lower()
        if suffix == ".xls":
            raise ValidationFailedError(
                "This is an older .xls file. Save it as .xlsx or CSV and try again.",
                code="unsupported_workbook",
            )
        if suffix == ".xlsx":
            remembered = (
                (saved.sheet_name, saved.header_signature) if saved and saved.sheet_name else None
            )
            workbook = await asyncio.to_thread(read_workbook, data, remembered_sheet=remembered)
            table = workbook.table
            imp.sheet_name = workbook.sheet_name
            imp.sheet_names = workbook.sheet_names
            imp.workbook_digest = sha256(data).hexdigest()
        else:
            table = locate_table(read_csv(data))
        await self.purge_expired(ctx.user_id)
        await self._preview_table(ctx, imp, table, saved)
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="import.started",
            entity_type="statement_import", entity_id=imp.id,
            data={"accountId": str(account.id), "fileName": imp.file_name,
                  "rowCount": imp.row_count, "sheetName": imp.sheet_name},
            request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        return await self._detail(ctx, imp)

    async def _preview_table(
        self,
        ctx: UserContext,
        imp: StatementImport,
        table: StatementTable,
        saved: StatementLayout | None,
    ) -> None:
        signature = header_signature(table.headers)
        if (
            saved is not None
            and saved.header_signature == signature
            and saved.sheet_name == imp.sheet_name
        ):
            columns = _columns_of(saved)
            imp.layout_confirmed = True
        else:
            columns = guess_columns(table.headers)
            if columns.date_column is not None:
                column = columns.date_column
                columns.date_order = guess_date_order(
                    [row[column] for row in table.data_rows if column < len(row)]
                )
            imp.layout_confirmed = False
        imp.header_cells = [cell_text(cell) for cell in table.headers]
        imp.header_signature = signature
        imp.layout = columns.model_dump()
        self._session.add(imp)
        await self._session.flush()
        raw_rows = [[cell_text(cell) for cell in row] for row in table.data_rows]
        await self._rebuild_rows(ctx, imp, columns, raw_rows)

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

    async def select_sheet(
        self,
        ctx: UserContext,
        import_id: uuid.UUID,
        sheet_name: str,
        data: bytes,
        *,
        preview_revision: int | None = None,
        request_id: str | None = None,
    ) -> ImportDetail:
        """Replace preview rows with a table from another sheet in the original upload."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "previewing":
            raise _not_previewing()
        _check_preview_revision(imp, preview_revision)
        check_file_size(data)
        if imp.workbook_digest is None or imp.workbook_digest != sha256(data).hexdigest():
            raise ValidationFailedError(
                "Choose the original Excel file to change the worksheet.", code="wrong_workbook"
            )
        if imp.sheet_name == sheet_name:
            return await self._detail(ctx, imp)
        workbook = await asyncio.to_thread(read_workbook, data, sheet_name=sheet_name)
        imp.sheet_name = workbook.sheet_name
        imp.preview_revision += 1
        saved = await self._saved_layout(ctx.user_id, imp.account_id)
        await self._preview_table(ctx, imp, workbook.table, saved)
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="import.sheet_selected",
            entity_type="statement_import", entity_id=imp.id,
            data={"sheetName": imp.sheet_name, "rowCount": imp.row_count}, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        return await self._detail(ctx, imp)

    async def save_layout(
        self,
        ctx: UserContext,
        import_id: uuid.UUID,
        columns: ColumnMapInput,
        *,
        preview_revision: int | None = None,
        request_id: str | None = None,
    ) -> ImportDetail:
        """Confirm (or correct) the layout, remember it for the account, and re-read the rows."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "previewing":
            raise _not_previewing()
        _check_preview_revision(imp, preview_revision)
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
        imp.preview_revision += 1
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
        preview_revision: int | None = None,
        request_id: str | None = None,
    ) -> ImportDetail:
        """Tick, untick or recategorise preview rows. A category the user picks is remembered
        as theirs, so only those rows teach merchant rules when the import is saved."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "previewing":
            raise _not_previewing()
        _check_preview_revision(imp, preview_revision)
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
        refresh_transfers = False
        for change in changes.rows:
            row = rows[change.id]
            if "transfer_account_id" in change.model_fields_set:
                await self._set_transfer_account(ctx, imp, row, change.transfer_account_id)
                refresh_transfers = True
            if change.is_selected is not None:
                self._tick(row, change.is_selected)
                refresh_transfers |= row.transfer_account_id is not None
            if change.category_id is not None:
                await self._set_category(ctx, row, change.category_id)
        if refresh_transfers:
            await self._session.flush()
            await self._refresh_transfer_matches(ctx, imp, await self._selected_transfers(ctx, imp))
        imp.preview_revision += 1
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
        if not selected:
            row.matched_transfer_id = None

    async def _set_category(self, ctx: UserContext, row: ImportRow, category_id: uuid.UUID) -> None:
        if row.transfer_account_id is not None:
            raise ValidationFailedError(
                "A transfer has no category.", details={"field": "categoryId"}
            )
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

    async def _set_transfer_account(
        self, ctx: UserContext, imp: StatementImport, row: ImportRow, other_id: uuid.UUID | None
    ) -> None:
        if row.status == "skipped":
            raise ValidationFailedError(
                "That row was skipped.", details={"field": "transferAccountId"}
            )
        if other_id is not None:
            other = await self._accounts.pick_for_transaction(
                ctx, other_id, field="transferAccountId"
            )
            _validate_transfer_account(imp, other)
            row.status = "transfer"
        elif row.transfer_account_id is not None:
            if row.matched_transaction_id is None:
                row.status = "to_import"
            else:
                row.status = "likely_duplicate"
                row.is_selected = False
        row.transfer_account_id = other_id
        row.transfer_account_chosen = True
        row.matched_transfer_id = None

    # -- saving and undoing -----------------------------------------------------------------

    async def confirm(
        self,
        ctx: UserContext,
        import_id: uuid.UUID,
        *,
        preview_revision: int | None = None,
        request_id: str | None = None,
    ) -> ImportDetail:
        """Save every ticked row as a transaction, all in one database transaction."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "previewing":
            raise _not_previewing()
        _check_preview_revision(imp, preview_revision)
        if not imp.layout_confirmed:
            raise ConflictError(
                "Confirm which columns are the date, description and amount first.",
                code="layout_not_confirmed",
            )
        await lock_statement_transfers(self._session, ctx.user_id)
        account = await self._accounts.pick_for_transaction(ctx, imp.account_id, field="accountId")
        await self._require_current_duplicate_matches(ctx, imp, request_id)
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
        keys = [row.fingerprint for row in rows if row.fingerprint is not None]
        already_saved = await self._saved_keys(ctx.user_id, keys)
        for row in rows:
            if row.fingerprint in already_saved:
                row.status = "skipped"
                row.note = "Already imported"
                row.is_selected = False
                row.matched_transfer_id = None
        rows = [row for row in rows if row.is_selected]
        discovered = await self._suggest_transfers(
            ctx,
            imp,
            [
                row
                for row in rows
                if not row.transfer_account_chosen and row.transfer_account_id is None
            ],
        )
        transfers = [row for row in rows if row.transfer_account_id is not None]
        await self._check_transfer_accounts(ctx, imp, transfers)
        matches_changed = await self._refresh_transfer_matches(ctx, imp, transfers, lock=True)
        if discovered or matches_changed:
            imp.preview_revision += 1
            record_audit(
                self._session, user_id=ctx.user_id, actor="user", action="import.transfer_matches_refreshed",
                entity_type="statement_import", entity_id=imp.id, request_id=request_id,
            )  # fmt: skip
            await self._session.commit()
            raise ConflictError(
                "Transfer matches changed. Review the updated preview and confirm again.",
                code="transfer_matches_changed",
            )
        ordinary = [row for row in rows if row.transfer_account_id is None]
        new_transfers = [row for row in transfers if row.matched_transfer_id is None]
        matched = [row for row in transfers if row.matched_transfer_id is not None]
        # Only a category the user chose in the preview teaches a merchant rule.
        chosen = [row for row in ordinary if row.category_source == "user"]
        guessed = [row for row in ordinary if row.category_source != "user"] + new_transfers
        created: dict[str, uuid.UUID] = {}
        for group, learns in ((chosen, True), (guessed, False)):
            items = [
                (_new_transaction(row, account.id, imp.currency), row.fingerprint or "")
                for row in group
            ]
            created.update(
                await self._transactions.create_imported(
                    ctx,
                    items,
                    source_ref=str(imp.id),
                    learn_merchants=learns,
                    request_id=request_id,
                )
            )
        for row in transfers:
            assert row.fingerprint is not None
            if transfer_id := row.matched_transfer_id or created.get(row.fingerprint):
                self._session.add(StatementTransferSide(
                    transfer_id=transfer_id, account_id=imp.account_id, import_row_id=row.id,
                    user_id=ctx.user_id, fingerprint=row.fingerprint,
                ))  # fmt: skip

        imp.status = "imported"
        imp.imported_count = len(created)
        imp.skipped_count = imp.row_count - len(created)
        imp.confirmed_at = self._clock.now()
        imp.expires_at = None
        imp.workbook_digest = None
        imp.sheet_names = None
        # The raw cells (references, balances) are not needed once the rows are saved.
        await self._session.execute(
            update(ImportRow).where(ImportRow.import_id == imp.id).values(raw_cells=[])
        )
        record_audit(
            self._session, user_id=ctx.user_id, actor="user", action="import.confirmed",
            entity_type="statement_import", entity_id=imp.id,
            data={"accountId": str(imp.account_id), "imported": len(created),
                  "matchedTransfers": len(matched), "rowCount": imp.row_count},
            request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        await self._transactions.bump_pending_generations()
        return await self._detail(ctx, imp)

    async def _require_current_duplicate_matches(
        self, ctx: UserContext, imp: StatementImport, request_id: str | None
    ) -> None:
        changed = await clear_stale_likely_duplicates(self._session, imp)
        if not changed:
            return
        imp.preview_revision += 1
        record_audit(
            self._session, user_id=ctx.user_id, actor="user",
            action="import.duplicate_matches_refreshed", entity_type="statement_import",
            entity_id=imp.id, data={"rowsChanged": changed}, request_id=request_id,
        )  # fmt: skip
        await self._session.commit()
        raise ConflictError(
            "Some duplicate matches changed. Review the latest rows and try again.",
            code="stale_preview",
        )

    async def undo(
        self, ctx: UserContext, import_id: uuid.UUID, *, request_id: str | None = None
    ) -> ImportDetail:
        """Soft-delete everything this import created and free its fingerprints for a re-import."""
        imp = await self._own_import(ctx.user_id, import_id, lock=True)
        if imp.status != "imported":
            raise ConflictError("Only a saved import can be undone.", code="import_not_imported")
        await lock_statement_transfers(self._session, ctx.user_id)
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
        # Undoing a matching statement only releases its side. Undoing the creating
        # statement releases any other sides too, so either statement can be replayed.
        await self._session.execute(
            delete(StatementTransferSide).where(
                StatementTransferSide.user_id == ctx.user_id,
                or_(
                    StatementTransferSide.transfer_id.in_(select(Transaction.id).where(*mine)),
                    StatementTransferSide.import_row_id.in_(
                        select(ImportRow.id).where(
                            ImportRow.import_id == imp.id, ImportRow.user_id == ctx.user_id
                        )
                    ),
                ),
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
        merchants = [extract_merchant(row.description) for row in parsed]
        wanted = [
            (
                StatementCategoryRow(row.position, kind, category_text(merchant, row.description)),
                merchant,
            )
            for row, merchant, fingerprint in zip(parsed, merchants, fingerprints, strict=True)
            if row.problem is None
            and fingerprint not in already_saved
            and (kind := _type_of(row.direction)) is not None
        ]
        choices = await pick_categories(
            ctx.user_id,
            categories=self._categories,
            rules=self._rules,
            wanted=wanted,
            categorizer=self._categorizer,
        )
        built = [
            self._preview_row(
                ctx, imp, choices.get(row.position), row, merchant, fingerprint, already_saved
            )
            for row, merchant, fingerprint in zip(parsed, merchants, fingerprints, strict=True)
        ]
        await self._session.execute(delete(ImportRow).where(ImportRow.import_id == imp.id))
        if built:
            await self._session.execute(insert(ImportRow), built)
            await mark_likely_duplicates(self._session, imp)
        imp.row_count = len(built)
        await self._suggest_transfers(ctx, imp)

    def _preview_row(
        self,
        ctx: UserContext,
        imp: StatementImport,
        choice: CategoryChoice | None,
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
        assert choice is not None
        return {
            **values, "merchant": merchant, "category_id": choice.category_id,
            "category_source": choice.source, "status": "to_import", "note": None,
            "is_selected": True,
        }  # fmt: skip

    async def _saved_keys(self, user_id: uuid.UUID, fingerprints: list[str]) -> set[str]:
        """Fingerprints already saved as transactions or linked to a transfer side."""
        if not fingerprints:
            return set()
        found = await self._session.scalars(
            select(Transaction.idempotency_key)
            .where(Transaction.user_id == user_id, Transaction.idempotency_key.in_(fingerprints))
            .union_all(
                select(StatementTransferSide.fingerprint).where(
                    StatementTransferSide.user_id == user_id,
                    StatementTransferSide.fingerprint.in_(fingerprints),
                )
            )
        )
        return {key for key in found if key}

    async def _suggest_transfers(
        self, ctx: UserContext, imp: StatementImport, rows: list[ImportRow] | None = None
    ) -> bool:
        if rows == []:
            return False
        accounts = await self._accounts.list_accounts(ctx)
        current = next((account for account in accounts if account.id == imp.account_id), None)
        if current is None or len(accounts) < 2:
            return False
        if rows is None:
            rows = list(
                await self._session.scalars(
                    select(ImportRow).where(
                        ImportRow.import_id == imp.id,
                        ImportRow.user_id == ctx.user_id,
                        ImportRow.status.in_(("to_import", "likely_duplicate")),
                    )
                )
            )
        suggestions: list[ImportRow] = []
        ambiguous: list[tuple[ImportRow, list[uuid.UUID]]] = []
        for row in rows:
            assert row.direction is not None
            targets = transfer_account_candidates(
                row.description, direction=row.direction, account=current, accounts=accounts
            )
            if len(targets) == 1:
                row.transfer_account_id = targets[0]
                row.status = "transfer"
                suggestions.append(row)
            elif targets:
                ambiguous.append((row, targets))
        inferred = await infer_transfer_accounts(
            self._session, user_id=ctx.user_id, account_id=imp.account_id,
            currency=imp.currency, ambiguous=ambiguous,
        )  # fmt: skip
        for row, _ in ambiguous:
            if target := inferred.get(row.id):
                row.transfer_account_id = target
                suggestions.append(row)
        await self._refresh_transfer_matches(ctx, imp, suggestions)
        for row in suggestions:
            if row.matched_transfer_id is not None:
                row.status = "transfer"
                row.is_selected = True
            elif row.id in inferred:
                # Another row took the only match, so its statement did not resolve the account.
                row.transfer_account_id = None
        return any(row.transfer_account_id is not None for row in suggestions)

    async def _selected_transfers(self, ctx: UserContext, imp: StatementImport) -> list[ImportRow]:
        return list(
            await self._session.scalars(
                select(ImportRow).where(
                    ImportRow.import_id == imp.id,
                    ImportRow.user_id == ctx.user_id,
                    ImportRow.status == "transfer",
                    ImportRow.is_selected.is_(True),
                )
            )
        )

    async def _check_transfer_accounts(
        self, ctx: UserContext, imp: StatementImport, rows: list[ImportRow]
    ) -> None:
        if not rows:
            return
        accounts = {account.id: account for account in await self._accounts.list_accounts(ctx)}
        for other_id in {row.transfer_account_id for row in rows if row.transfer_account_id}:
            other = accounts.get(other_id)
            if other is None:
                # Archived accounts can appear in a preview created earlier.
                other = await self._accounts.pick_for_transaction(
                    ctx, other_id, field="transferAccountId"
                )
            _validate_transfer_account(imp, other)

    async def _refresh_transfer_matches(
        self,
        ctx: UserContext,
        imp: StatementImport,
        rows: list[ImportRow],
        *,
        lock: bool = False,
    ) -> bool:
        matches = await match_statement_transfers(
            self._session, user_id=ctx.user_id, account_id=imp.account_id,
            currency=imp.currency, rows=rows, lock=lock,
        )  # fmt: skip
        changed = False
        for row in rows:
            match = matches.get(row.id)
            if match != row.matched_transfer_id:
                row.matched_transfer_id = match
                changed = True
        return changed

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
        assert layout.date_column is not None
        fields = layout.model_dump(by_alias=False) | {
            "header_signature": imp.header_signature,
            "sheet_name": imp.sheet_name,
        }
        # Two different previews for the same account can confirm a layout at the same time.
        await self._session.execute(
            pg_insert(StatementLayout)
            .values(id=uuid7(), user_id=user_id, account_id=imp.account_id, **fields)
            .on_conflict_do_update(
                constraint="uq_statement_layouts_account",
                set_=fields | {"updated_at": func.now()},
                where=StatementLayout.user_id == user_id,
            )
        )

    # -- views ------------------------------------------------------------------------------

    async def _own_import(
        self,
        user_id: uuid.UUID,
        import_id: uuid.UUID,
        *,
        lock: bool = False,
        read_lock: bool = False,
    ) -> StatementImport:
        # Ownership is part of the WHERE clause: another user's import is simply "not found".
        query = select(StatementImport).where(
            StatementImport.id == import_id, StatementImport.user_id == user_id
        )
        if lock or read_lock:
            query = query.with_for_update(read=read_lock).execution_options(populate_existing=True)
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
        # Read the parent and all its rows under the same lock. A mutation replaces rows only
        # while it holds an exclusive lock on the parent.
        imp = await self._own_import(ctx.user_id, imp.id, read_lock=True)
        account = await self._session.get(Account, imp.account_id)
        assert account is not None
        other = aliased(Account)
        row_filter = [ImportRow.import_id == imp.id, ImportRow.user_id == ctx.user_id]
        if status is not None:
            row_filter.append(ImportRow.status == status)
        total = await self._session.scalar(
            select(func.count()).select_from(ImportRow).where(*row_filter)
        )
        # Bound the input before joining duplicate details. The materialized page prevents
        # a poor nested-loop plan from scanning the entire imported ledger for each row.
        page_ids = (
            select(ImportRow.id)
            .where(*row_filter)
            .order_by(ImportRow.position)
            .offset(max(offset, 0))
            .limit(max(1, min(limit, MAX_PAGE_SIZE)))
            .cte("import_detail_page")
            .prefix_with("MATERIALIZED")
        )
        rows = (
            await self._session.execute(
                select(ImportRow, Category, Transaction, other)
                .join(page_ids, page_ids.c.id == ImportRow.id)
                .outerjoin(Category, Category.id == ImportRow.category_id)
                .outerjoin(Transaction, current_duplicate_match(imp))
                .outerjoin(
                    other,
                    (other.id == ImportRow.transfer_account_id) & (other.user_id == ctx.user_id),
                )
                .order_by(ImportRow.position)
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
            sheet_name=imp.sheet_name,
            sheet_names=imp.sheet_names or [],
            preview_revision=imp.preview_revision,
            layout_confirmed=imp.layout_confirmed,
            counts=await self._counts(imp),
            rows=[
                _preview_row_view(row, category, match, other_account, imp.currency, ctx.locale)
                for row, category, match, other_account in rows
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
                    func.count(ImportRow.matched_transfer_id),
                )
                .where(ImportRow.import_id == imp.id)
                .group_by(ImportRow.status, ImportRow.is_selected, ImportRow.direction)
            )
        ).all()
        by_status: dict[str, int] = defaultdict(int)
        selected = selected_out = selected_in = matched_transfers = 0
        for status, is_selected, direction, count, amount, matches in grouped:
            by_status[status] += count
            if is_selected:
                selected += count
                matched_transfers += matches
                if direction == "out":
                    selected_out += int(amount or 0)
                elif direction == "in":
                    selected_in += int(amount or 0)
        return PreviewCounts(
            to_import=by_status["to_import"],
            skipped=by_status["skipped"],
            likely_duplicates=by_status["likely_duplicate"],
            transfers=by_status["transfer"],
            matched_transfers=matched_transfers,
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
    row: ImportRow,
    category: Category | None,
    matched: Transaction | None,
    other: Account | None,
    currency: str,
    locale: str,
) -> PreviewRow:
    is_transfer = row.status == "transfer"
    matches_existing = row.matched_transfer_id is not None
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
        merchant=None if is_transfer else row.merchant,
        category=(
            CategoryRef(id=category.id, slug=category.slug, name=category.name, icon=category.icon)
            if category and not is_transfer
            else None
        ),
        category_source=None if is_transfer else row.category_source,
        transfer_account=AccountRef(id=other.id, name=other.name, kind=other.kind)
        if other
        else None,
        matches_existing_transfer=matches_existing,
        status=row.status,
        note="Already recorded as a transfer" if matches_existing else row.note,
        is_selected=row.is_selected,
        matched_transaction=(
            MatchedTransaction(
                id=matched.id, description=matched.description, source=matched.source
            )
            if matched
            else None
        ),
    )


def _new_transaction(row: ImportRow, account_id: uuid.UUID, currency: str) -> NewTransaction:
    row_type = _type_of(row.direction)
    assert row_type is not None and row.amount_minor is not None and row.occurred_on is not None
    if (other_id := row.transfer_account_id) is not None:
        from_id, to_id = (
            (account_id, other_id) if row.direction == "out" else (other_id, account_id)
        )
        return NewTransaction(
            type="transfer", amount_minor=row.amount_minor, currency=currency,
            occurred_on=row.occurred_on, category_id=None, description=row.description,
            merchant=None, payment_method=None, account_id=from_id, to_account_id=to_id,
        )  # fmt: skip
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


def _validate_transfer_account(imp: StatementImport, other: AccountView) -> None:
    details = {"field": "transferAccountId"}
    if imp.account_id == other.id:
        raise ValidationFailedError("A transfer needs two different accounts.", details=details)
    if imp.currency != other.currency:
        raise ValidationFailedError(
            "Transfers between currencies are not supported.", details=details
        )
