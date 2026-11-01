"""Statement imports over HTTP: upload a statement, adjust its preview, save it, undo it."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, Response, UploadFile

from finance_api.deps import ContainerDep, RequestIdDep, SessionDep, UserContextDep
from finance_core.errors import PayloadTooLargeError
from finance_core.imports.schemas import (
    ColumnMapInput,
    ImportDetail,
    ImportSummary,
    RowChanges,
    RowStatusField,
)
from finance_core.imports.service import ImportService
from finance_core.imports.table import MAX_FILE_BYTES

router = APIRouter(prefix="/api/v1/imports", tags=["imports"])


def _service(session: SessionDep, container: ContainerDep) -> ImportService:
    return ImportService(session, clock=container.clock, generation=container.generation)


ServiceDep = Annotated[ImportService, Depends(_service)]


@router.post("", status_code=201)
async def upload_statement(
    ctx: UserContextDep,
    service: ServiceDep,
    request_id: RequestIdDep,
    account_id: Annotated[uuid.UUID, Form(alias="accountId")],
    file: Annotated[UploadFile, File()],
) -> ImportDetail:
    # Read one byte past the limit so an oversized file is refused without loading all of it.
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise PayloadTooLargeError(
            "That file is over 5 MB. Export a shorter date range and try again.",
            code="file_too_large",
        )
    return await service.start(
        ctx,
        account_id=account_id,
        file_name=file.filename or "statement.csv",
        data=data,
        request_id=request_id,
    )


@router.get("")
async def list_imports(ctx: UserContextDep, service: ServiceDep) -> list[ImportSummary]:
    return await service.list_imports(ctx)


@router.get("/{import_id}")
async def get_import(
    import_id: uuid.UUID,
    ctx: UserContextDep,
    service: ServiceDep,
    status: Annotated[RowStatusField | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> ImportDetail:
    return await service.get(ctx, import_id, status=status, offset=offset, limit=limit)


@router.put("/{import_id}/layout")
async def save_layout(
    import_id: uuid.UUID,
    body: ColumnMapInput,
    ctx: UserContextDep,
    service: ServiceDep,
    request_id: RequestIdDep,
) -> ImportDetail:
    return await service.save_layout(ctx, import_id, body, request_id=request_id)


@router.patch("/{import_id}/rows")
async def update_rows(
    import_id: uuid.UUID,
    body: RowChanges,
    ctx: UserContextDep,
    service: ServiceDep,
    request_id: RequestIdDep,
) -> ImportDetail:
    return await service.update_rows(ctx, import_id, body, request_id=request_id)


@router.post("/{import_id}/confirm")
async def confirm_import(
    import_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> ImportDetail:
    return await service.confirm(ctx, import_id, request_id=request_id)


@router.post("/{import_id}/undo")
async def undo_import(
    import_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> ImportDetail:
    return await service.undo(ctx, import_id, request_id=request_id)


@router.delete("/{import_id}", status_code=204)
async def discard_import(
    import_id: uuid.UUID, ctx: UserContextDep, service: ServiceDep, request_id: RequestIdDep
) -> Response:
    await service.discard(ctx, import_id, request_id=request_id)
    return Response(status_code=204)
