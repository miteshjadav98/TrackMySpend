# Phase 5: charts and deterministic insights

Status: ready-for-agent
Integration branch: `phase-5/integration`
Tickets: `issues/` in this directory

## Level and assumptions

MoneyMoney is low-traffic today (assume fewer than 1,000 daily users and less than 10 peak
requests per second), but reporting is a production-grade financial read path: incorrect or
irreproducible totals are worse than a slow chart. One modular monolith, Postgres and the existing
generation-keyed Redis cache are enough. Design for up to 100,000 live transactions for one user,
a five-year report range, a cold-report p95 below one second and 99.9% service availability.

The first scaling step is measuring and indexing slow SQL, not adding a queue, warehouse, second
database or materialized-view pipeline. Revisit that only if cold report queries exceed one second
at the assumed per-user volume or reports become about 30% of database load.

## Problem statement

MoneyMoney can answer a total for one period, but it does not show how spending changes over time,
which categories or merchants drive it, or whether the current period differs from the comparable
previous period. A user must ask several chat questions and mentally assemble the answer. Users
with more than one currency also need the product to be explicit: adding rupees and dollars would
produce a confident-looking number with no financial meaning.

## Solution

Add a **Reports** page backed by deterministic SQL read models. The page offers familiar period
presets and a custom range, shows one currency at a time, and combines exact KPI totals with an
expense trend, category breakdown, top merchants and a small set of rule-based insights. A user can
drill from a category or merchant into the existing Transactions page with matching filters.

Charts are a presentation of server-produced values. The model never calculates totals, creates
data points or converts currencies. Chat can request the same report data and render it with one
fixed, versioned interaction; Phase 5 does not adopt AG-UI or A2UI.

## Currency policy

1. Every monetary total, comparison, trend, category and merchant series is grouped by its ISO
   currency.
2. The UI shows one selected currency at a time, with the profile's base currency first. When a
   period contains several currencies, tabs/chips make the separation visible.
3. MoneyMoney never adds or compares amounts from different currencies and never labels one as a
   base-currency equivalent.
4. Transaction counts may be combined because they are counts, not money; any monetary KPI remains
   inside its currency section.
5. Phase 5 does not fetch exchange rates. Reproducible conversion would require a named rate source,
   stored historical rates, rate dates, rounding rules and correction policy; that is a separate
   future phase.
6. Cross-currency transfers and converted friend balances remain out of scope. This phase records
   the policy; it does not pretend that choosing a base currency supplies an exchange rate.

This policy is deliberately conservative. Its cost is that MoneyMoney cannot show one worldwide
net-spend number. Its benefit is that every number remains exact, reproducible and explainable.

## User stories

**Opening and filtering reports**

1. As a user, I want a Reports item in the main navigation, so that I can inspect my money without
   phrasing a chat question.
2. As a user, I want presets for this month, last month, the last 3 months, the last 6 months, this
   year and last year, plus a custom range, so that common comparisons take one tap.
3. As a user, I want every report to state its inclusive dates and transaction count, so that I can
   see exactly what was counted.
4. As a user with several currencies, I want a separate tab for each currency and my base currency
   first, so that unlike amounts never mix.
5. As a user with no data in a period, I want a useful empty state and a link to add or import
   transactions, not an empty chart frame.

**Understanding a period**

6. As a user, I want spent, received and net totals for the selected currency, so that the headline
   is clear.
7. As a user, I want those totals compared with the immediately preceding period of equal length,
   so that a partial current month is not compared with a complete previous month.
8. As a user, I want an expense and income trend over the period, so that spikes and direction are
   visible.
9. As a user, I want spending by category, with amount and share, so that I know where money went.
10. As a user, I want top merchants, with amount and transaction count, so that repeated spending is
    visible; transactions without a merchant stay under "Other merchants" rather than disappearing.
11. As a user, I want accessible tables containing every chart value, so that charts are not the
    only way to read the report.
12. As a user, I want chart hover/focus details and layouts that work on mobile, dark mode and with
    reduced motion, so that the report is usable in my environment.

**Insights and drill-down**

13. As a user, I want short facts such as spending change, largest category and largest merchant,
    so that the important parts stand out.
14. As a user, I want each fact to name its period, currency and supporting amount, so that it is
    auditable rather than vague advice.
15. As a user, I want to select a category, merchant or trend bucket and open the Transactions page
    with the corresponding filters, so that I can inspect the underlying rows.
16. As a user, I do not want generic financial advice, budgets, forecasts or anomaly claims, so that
    the product does not overstate what historical transaction data proves.

**Chat**

17. As a user, I want requests such as "show my spending trend for six months" or "where did my
    money go this month?" to render the same trusted report data in chat.
18. As a user, I want a chat report card to link to the full Reports page with the same period and
    currency selected.
19. As a user, I want ordinary total questions to keep their current compact summary card rather
    than turning every answer into a chart.

**Correctness and safety**

20. As a user, I want deleted transactions and transfers excluded and my own shared-expense share
    included, matching every existing summary.
21. As a user, I want report values to refresh after create, edit, delete, restore, import, undo and
    shared-expense changes, so that cached charts never contradict the ledger.
22. As a user, I want another user's reporting data to remain inaccessible, so that analytics never
    weaken row isolation.
23. As a user, I want invalid or overly large date ranges rejected clearly, so that report requests
    stay bounded.

## Reporting contract

Add a report read model alongside the existing `SpendingSummary`; do not replace the current
summary endpoint or its chat contract.

- `GET /api/v1/reports/overview` accepts the existing period parameters (`period`, `month`,
  `start`, `end`, `days`). New 3- and 6-month presets are expressed as bounded day/range values by
  the client or added as explicit period kinds if doing so keeps URLs stable.
- The response includes the requested `period`, an equal-length `comparisonPeriod`, base currency,
  combined transaction count, generation time and a list of currency reports.
- Each currency report contains exact income, expense and net totals; previous-period totals;
  absolute changes and nullable percentages; trend buckets; expense categories; and top merchants.
- Percentage change is `null` when the previous amount is zero. The UI says "No previous spending"
  instead of displaying infinity or a misleading 100%.
- Trend buckets are deterministic and capped: daily for up to 62 days, weekly for up to 366 days,
  and monthly beyond that. Buckets cover the complete requested range, including zero-value gaps,
  and carry explicit inclusive start/end dates.
- Categories are exhaustive and sum to the expense total. Merchant output is capped to the top ten
  plus an `Other merchants` bucket, so payload and chart cardinality stay bounded.
- All money remains integer minor units plus ISO currency and formatted display strings, using the
  user's locale. The frontend never performs financial arithmetic.
- The response is cached with the existing per-user data generation, date range, locale and base
  currency in the key. Redis failure falls back to Postgres.
- Unknown users never reach the service; every SQL statement is scoped by authenticated
  `UserContext.user_id`.

## Comparison and insights

- The comparison period has the same number of days and ends the day before the requested period.
  It is clipped only by the existing earliest allowed report date; an unavailable comparison is
  represented explicitly.
- Insights are deterministic typed facts, not generated prose. Phase 5 supports: spending change
  from the comparison period, largest expense category and largest merchant. Facts are omitted
  when their prerequisites are absent.
- Each fact carries structured evidence (currency, current amount, previous amount or share, and
  relevant category/merchant key). The API may provide a short display sentence, but tests assert
  the underlying values and wording.
- No forecasting, budget recommendation, anomaly detection, causal claim or peer comparison.

## Web contract

- Add `/reports` to the authenticated app and main sidebar.
- The URL owns the selected period, custom dates and currency so reload, history and chat deep links
  reproduce the same view. Invalid parameters fall back visibly rather than silently changing the
  requested dates.
- Use a small MoneyMoney-owned chart layer built from semantic HTML and SVG/CSS. Do not accept raw
  chart configuration or executable formatters from the server. A chart library may be introduced
  only if it materially improves accessibility and keeps bundle/build checks acceptable.
- Every chart has a table alternative and an accessible name. Colour is not the only encoding;
  income and expense series also differ by label/shape. Respect reduced-motion preferences.
- Category and merchant drill-down reuse the Transactions route/query filters. Add a merchant
  filter to the transaction API only if exact drill-down cannot be expressed by the existing text
  filter; never approximate a drill-down without labelling it.

## Chat contract

- Add one fixed `report` interaction payload containing the same server-produced report view or a
  bounded subset plus a deep link. It is versioned and persisted like existing interactions.
- Extend understanding only for explicit trend, breakdown or insight requests. Existing summary
  questions stay on the current `summarize` path.
- The workflow chooses period and report kind; `ReportService` supplies every value. The LLM never
  receives responsibility for arithmetic, grouping or currency conversion.
- The offline parser covers the supported report phrases, and the prompt/eval set measures any new
  intent over repeated runs before release.

## Testing and non-functional requirements

- Integration tests use real Postgres and cover single and multiple currencies, period boundaries,
  zero gaps, comparison periods, category/merchant reconciliation, transfers, deleted rows, shared
  expenses, cache invalidation and user isolation.
- Unit tests cover bucket selection/filling, percentage-change edge cases and typed insight rules.
- Contract generation, strict Python checks, all tests, database drift, web typecheck/lint and
  production build pass.
- Browser/component tests cover empty, one-currency and multi-currency reports; URL restoration;
  drill-down links; narrow screens; keyboard focus; dark mode and table fallbacks.
- Log report kind, range length, result cardinality, cache hit/miss and duration without logging
  transaction descriptions, merchant names or amounts.
- Cap a response at 120 trend buckets, all categories and 11 merchant buckets. A custom range stays
  within the existing five-year maximum.

## Scale and failure plan

- First bottleneck: date-range aggregation scans too many rows for one user. Measure cold duration;
  then inspect the query plan, fix N+1 work and add a covering/partial index before considering any
  new datastore.
- Redis down: compute from Postgres and return the same response, slightly slower.
- Empty or partial data: return a valid report with explicit empty collections; never synthesize
  data points.
- One dimension query fails: fail the request rather than combine results from different ledger
  generations. The next request retries from a consistent database view.
- Rollback: the phase adds read paths and UI only; the existing summary endpoint remains intact, so
  removing the Reports navigation/route rolls back without a data migration.

## Out of scope

- FX conversion, exchange-rate storage, combined monetary totals and cross-currency transfers.
- Budgets, goals, forecasts, anomaly detection, recommendations or external benchmarks.
- PDF/Excel report export, scheduled reports and email delivery.
- AG-UI, A2UI or arbitrary model-composed chart layouts.
- A warehouse, OLAP database, queue, event bus, materialized-view pipeline or background report
  jobs.
- Account balances and net-worth reporting.

