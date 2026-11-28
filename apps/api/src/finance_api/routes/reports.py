from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query

from finance_api.deps import ContainerDep, SessionDep, UserContextDep
from finance_core.dates import DateRange, PeriodError, PeriodKind, resolve_period
from finance_core.errors import ValidationFailedError
from finance_core.reports.schemas import ReportOverview, SpendingSummary
from finance_core.reports.service import ReportService

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _period(
    ctx: UserContextDep,
    container: ContainerDep,
    period: PeriodKind,
    month: str | None,
    start: date | None,
    end: date | None,
    days: int | None,
) -> DateRange:
    try:
        return resolve_period(
            period,
            ctx.today(container.clock),
            month=month,
            start=start.isoformat() if start else None,
            end=end.isoformat() if end else None,
            days=days,
        )
    except PeriodError as exc:
        raise ValidationFailedError(str(exc), details={"field": "period"}) from None


def _service(session: SessionDep, container: ContainerDep) -> ReportService:
    return ReportService(
        session,
        clock=container.clock,
        redis=container.redis,
        generation=container.generation,
        cache_ttl_seconds=container.settings.cache_summary_ttl_seconds,
    )


@router.get("/summary")
async def get_summary(
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    period: Annotated[PeriodKind, Query()] = "this_month",
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    days: Annotated[int | None, Query(ge=1, le=1830)] = None,
) -> SpendingSummary:
    """Totals for a period in the user's own calendar, grouped by currency."""
    date_range = _period(ctx, container, period, month, start, end, days)
    return await _service(session, container).summary(ctx, date_range)


@router.get("/overview")
async def get_overview(
    ctx: UserContextDep,
    session: SessionDep,
    container: ContainerDep,
    period: Annotated[PeriodKind, Query()] = "this_month",
    month: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    days: Annotated[int | None, Query(ge=1, le=1830)] = None,
) -> ReportOverview:
    """Chart-ready exact aggregates, always separated by currency."""

    date_range = _period(ctx, container, period, month, start, end, days)
    return await _service(session, container).overview(ctx, date_range)
