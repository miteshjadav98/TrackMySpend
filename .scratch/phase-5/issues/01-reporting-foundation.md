# 01: Reporting read model and currency policy

**What to build:** Add the deterministic report overview contract: exact current and equal-length
comparison totals, bounded trend buckets, category totals and top merchants, always separated by
currency. Record the no-conversion policy in an ADR.

Spec: `../spec.md` → Currency policy; Reporting contract; Comparison and insights (data only);
Testing and non-functional requirements.

**Blocked by:** None

**Status:** ready-for-agent

- [ ] ADR 0002 records that monetary totals remain per currency until a named, stored historical FX
  policy exists; architecture and glossary terminology agree.
- [ ] `ReportService` exposes an overview read model with requested and equal-length comparison
  periods, per-currency totals, absolute/nullable percentage changes, trends, categories and top
  merchants; transfers and deleted rows remain excluded.
- [ ] Trend buckets are daily/weekly/monthly by the spec, include zero gaps and stay within the
  response cap; merchant output is top ten plus `Other merchants` and reconciles to expenses with a
  merchant dimension.
- [ ] `GET /api/v1/reports/overview` supports the existing bounded period parameters, is user-scoped
  and uses the generation-keyed cache with Postgres fallback.
- [ ] Integration tests cover period boundaries, partial-period comparison, one and several
  currencies, transfers, deleted/shared rows, cache invalidation and user isolation.
- [ ] Unit tests cover bucket selection/filling and percentage-change zero cases.
- [ ] Contracts regenerate; API checks, full pytest and Alembic drift checks pass.

