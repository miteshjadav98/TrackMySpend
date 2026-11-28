# ruff: noqa: T201
"""Measure uncached report reads on 100k synthetic rows, rolled back in the test DB.

Example: uv run python -m tests.evals.benchmark_reports --output benchmark.json
No live ledger is touched; the generated user and rows never commit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import make_url

from finance_core.clock import FixedClock
from finance_core.database.engine import create_engine, create_session_factory
from finance_core.dates import DateRange
from finance_core.reports.service import ReportService
from finance_core.transactions.schemas import TransactionQuery
from finance_core.transactions.service import TransactionService
from finance_core.users.context import UserContext
from tests.conftest import make_settings


async def benchmark() -> dict[str, object]:
    """Cold means bypassing Redis; this does not evict the Postgres/OS buffer cache."""
    settings = make_settings()
    if make_url(settings.sqlalchemy_url).database != "moneymoney_test":
        raise ValueError("Benchmark requires the isolated moneymoney_test database")
    engine = create_engine(settings)
    results: list[dict[str, object]] = []
    user_id = uuid.uuid4()
    ctx = UserContext(user_id, "INR", "Asia/Kolkata", "en-IN")
    clock = FixedClock(datetime(2026, 11, 24, 6, tzinfo=UTC))
    try:
        async with create_session_factory(engine)() as session:
            try:
                await session.execute(
                    text(
                        "INSERT INTO identity.users (id,email,display_name,status) "
                        "VALUES (:user_id,:email,'Benchmark','active')"
                    ),
                    {"user_id": user_id, "email": f"{user_id}@benchmark.test"},
                )
                await session.execute(
                    text("""
                    INSERT INTO ledger.transactions
                        (id,user_id,type,amount_minor,currency,occurred_on,merchant,source,version)
                    SELECT gen_random_uuid(), :user_id,
                        CASE WHEN n % 5 = 0 THEN 'income' ELSE 'expense' END,
                        (n % 100000) + 1,
                        CASE WHEN n % 3 = 0 THEN 'USD' ELSE 'INR' END,
                        DATE '2021-11-21' + (n % 1830),
                        CASE WHEN n % 17 = 0 THEN NULL ELSE 'Merchant ' || (n % 1000) END,
                        'manual', 1
                    FROM generate_series(1, 100000) AS n
                """),
                    {"user_id": user_id},
                )
                service = ReportService(session, clock=clock)  # Redis deliberately absent
                for label, start, end in (
                    ("month", date(2026, 11, 1), date(2026, 11, 24)),
                    ("year", date(2026, 1, 1), date(2026, 11, 24)),
                    ("five_years", date(2021, 11, 21), date(2026, 11, 24)),
                ):
                    period = DateRange(start, end, label)
                    times = []
                    payload = None
                    for _ in range(20):
                        started = time.perf_counter()
                        payload = await service.overview(ctx, period)
                        serialized = payload.model_dump_json().encode()
                        times.append((time.perf_counter() - started) * 1000)
                    assert payload is not None
                    assert all(
                        len(item.trend) <= 120 and len(item.top_merchants) <= 11
                        for item in payload.currencies
                    )
                    results.append(
                        {
                            "period": label,
                            "rangeDays": period.days,
                            "samples": len(times),
                            "p50Ms": round(statistics.median(times), 2),
                            "p95Ms": round(
                                statistics.quantiles(times, n=20, method="inclusive")[18], 2
                            ),
                            "maxMs": round(max(times), 2),
                            "jsonBytes": len(serialized),
                            "currencies": len(payload.currencies),
                            "maxTrendBuckets": max(len(item.trend) for item in payload.currencies),
                            "maxMerchantBuckets": max(
                                len(item.top_merchants) for item in payload.currencies
                            ),
                            "transactionCount": payload.transaction_count,
                        }
                    )
                transactions = TransactionService(session, clock=clock)
                for name, kwargs in (
                    ("named_merchant", {"merchant_key": "merchant 1"}),
                    ("other_merchants", {"other_merchants": True}),
                ):
                    times = []
                    query = TransactionQuery(
                        type="expense",
                        currency="INR",
                        date_from=date(2021, 11, 21),
                        date_to=date(2026, 11, 24),
                        **kwargs,
                    )
                    for _ in range(20):
                        started = time.perf_counter()
                        page = await transactions.search(ctx, query)
                        serialized = page.model_dump_json().encode()
                        times.append((time.perf_counter() - started) * 1000)
                    results.append(
                        {
                            "period": name,
                            "rangeDays": 1830,
                            "samples": len(times),
                            "p50Ms": round(statistics.median(times), 2),
                            "p95Ms": round(
                                statistics.quantiles(times, n=20, method="inclusive")[18], 2
                            ),
                            "maxMs": round(max(times), 2),
                            "jsonBytes": len(serialized),
                            "pageRows": len(page.items),
                        }
                    )
            finally:
                await session.rollback()
    finally:
        await engine.dispose()
    return {
        "recordedAt": datetime.now(UTC).isoformat(),
        "syntheticTransactions": 100000,
        "database": "Postgres 17, local Docker",
        "cache": "Redis bypassed; DB/OS buffers retained",
        "distribution": "two currencies, 1000 merchants, five years, 80% expenses",
        "results": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(benchmark())
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    if any(item["p95Ms"] >= 1000 for item in result["results"]):  # type: ignore[union-attr,index]
        raise SystemExit("Cold report p95 exceeds one second")


if __name__ == "__main__":
    main()
