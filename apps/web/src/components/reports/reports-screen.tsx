"use client";

import type { MetricComparison, ReportOverview } from "@moneymoney/contracts";
import { ArrowDownLeft, ArrowUpRight, ChartNoAxesCombined, RefreshCw, Wallet } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { type FormEvent, useState, useTransition } from "react";

import { Button } from "@/components/ui/button";
import { ReportCharts } from "@/components/reports/report-charts";
import { Field, Input, Select } from "@/components/ui/field";
import { useMe, useReport } from "@/lib/queries";
import {
  EARLIEST_REPORT_DATE, REPORT_PERIODS, readReportFilters, reportHref,
  reportMonthRange, reportRangeError, reportToday,
} from "@/lib/report-filters";

/** Use absolute calendar dates so a shared report never labels an old day as “Today”. */
function dateLabel(value: string, locale: string): string {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString(locale, {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
}

function periodLabel(period: ReportOverview["period"], locale: string) {
  return `${dateLabel(period.start, locale)} – ${dateLabel(period.end, locale)}`;
}

/** An unapplied range is a draft. Only Apply changes the URL and requests new report data. */
function CustomRange({ start, end, onApply }: {
  start: string; end: string; onApply: (start: string, end: string) => void;
}) {
  const [from, setFrom] = useState(start);
  const [to, setTo] = useState(end);
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const validation = reportRangeError(from, to);
    setError(validation);
    if (!validation) onApply(from, to);
  }

  return (
    <form onSubmit={submit} noValidate className="mt-4 border-t border-line pt-4">
      <div className="grid items-end gap-3 sm:grid-cols-[1fr_1fr_auto]">
        <Field label="Start date">
          {({ id }) => <Input id={id} type="date" value={from} min={EARLIEST_REPORT_DATE}
            aria-invalid={Boolean(error)} aria-describedby={error ? "report-range-error" : "report-range-hint"}
            onChange={(event) => { setFrom(event.target.value); setError(null); }} />}
        </Field>
        <Field label="End date">
          {({ id }) => <Input id={id} type="date" value={to} min={from || EARLIEST_REPORT_DATE}
            aria-invalid={Boolean(error)} aria-describedby={error ? "report-range-error" : "report-range-hint"}
            onChange={(event) => { setTo(event.target.value); setError(null); }} />}
        </Field>
        <Button type="submit" variant="primary">Apply dates</Button>
      </div>
      <p id="report-range-hint" className="mt-2 text-xs text-ink-faint">Both dates are included. Choose up to 5 years (1,830 days).</p>
      {error ? <p id="report-range-error" role="alert" className="mt-2 text-sm text-danger">{error}</p> : null}
    </form>
  );
}

/** Present the server's exact current, previous and change values without monetary arithmetic. */
function MetricCard({ label, metric, locale, icon, note, noPrevious }: {
  label: string; metric: MetricComparison; locale: string; icon: React.ReactNode;
  note: string; noPrevious: string;
}) {
  const percentage = metric.changePercent;
  const prefix = metric.change.amountMinor > 0 ? "+" : "";
  return (
    <section aria-label={label} className="min-w-0 rounded-[var(--radius-card)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium text-ink-soft">{label}</h2>
        <span className="rounded-lg bg-sky-wash p-2 text-sky-deep">{icon}</span>
      </div>
      <p className="figure mt-4 text-3xl font-semibold break-words">{metric.current.formatted}</p>
      <p className="mt-1 text-xs text-ink-faint">{note}</p>
      <div className="mt-5 border-t border-line pt-3 text-sm">
        <p className="text-ink-soft">Previous: <span className="figure font-medium text-ink">{metric.previous.formatted}</span></p>
        <p className="mt-1 text-ink-soft">
          Change: <span className="figure font-medium text-ink">{prefix}{metric.change.formatted}</span>
          {percentage !== null ? ` (${percentage > 0 ? "+" : ""}${percentage.toLocaleString(locale, { maximumFractionDigits: 1 })}%)` : null}
        </p>
        {percentage === null ? <p className="mt-1 text-xs text-ink-faint">{noPrevious}</p> : null}
      </div>
    </section>
  );
}

function EmptyReport({ currency }: { currency?: string }) {
  return (
    <section aria-label="No report data" className="mt-6 rounded-[var(--radius-card)] border border-dashed border-line-strong bg-surface px-5 py-12 text-center">
      <ChartNoAxesCombined aria-hidden className="mx-auto mb-4 size-8 text-sky-deep" />
      <h2 className="display text-xl font-semibold">{currency ? `No ${currency} transactions in this period` : "A fresh page for your money"}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-ink-soft">
        {currency ? "Choose another currency or a wider date range to see your report." : "There are no transactions in this period. Try a wider date range, or add your first transaction to get started."}
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-3 text-sm font-medium text-sky-deep">
        <Link href="/transactions" className="rounded-lg border border-line-strong px-4 py-2 hover:bg-sky-wash">Add or import transactions</Link>
        <Link href="/chat" className="rounded-lg px-4 py-2 hover:bg-sky-wash">Record in chat</Link>
      </div>
    </section>
  );
}

/** Authenticated reports with URL-owned filters and one currency's server-produced KPIs. */
export function ReportsScreen() {
  const params = useSearchParams();
  const router = useRouter();
  const [navigating, startTransition] = useTransition();
  const me = useMe();
  const locale = me.data?.profile.locale ?? "en-IN";
  const today = reportToday(me.data?.profile.timezone ?? "Asia/Kolkata");
  const filters = readReportFilters(params, today);
  const report = useReport(filters.query);
  const data = report.data;
  const currency = filters.currency ?? data?.baseCurrency ?? me.data?.profile.baseCurrency ?? "INR";
  // Keep the base currency visible even if this period only has foreign-currency transactions.
  const currencies = [...new Set([
    data?.baseCurrency ?? me.data?.profile.baseCurrency ?? "INR",
    ...(data?.currencies.map((item) => item.currency) ?? []),
    currency,
  ])];
  const selected = data?.currencies.find((item) => item.currency === currency);

  function navigate(href: string) {
    startTransition(() => router.push(href, { scroll: false }));
  }

  function selectPeriod(period: string) {
    let extra: Record<string, string> = {};
    if (period === "range") extra = { start: data?.period.start ?? today, end: data?.period.end ?? today };
    if (period === "last_3_months" || period === "last_6_months") {
      extra = reportMonthRange(today, period === "last_3_months" ? 3 : 6);
    }
    navigate(reportHref(period, filters.currency, extra));
  }

  function selectCurrency(value: string) {
    // Preserve exact dates and any supported chat/deep-link period parameters.
    const next = new URLSearchParams(params.toString());
    next.set("currency", value);
    navigate(`/reports?${next.toString()}`);
  }

  const customOption = !REPORT_PERIODS.some(([value]) => value === filters.period);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
        <header className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="mb-2 text-xs font-semibold tracking-widest text-sky-deep uppercase">Your money, in perspective</p>
            <h1 className="display text-[1.9rem] leading-tight font-semibold">Reports</h1>
            <p className="mt-2 max-w-xl text-sm text-ink-soft">A clear view of what came in and what went out. Every currency stays separate.</p>
          </div>
          <Button icon={<RefreshCw aria-hidden className="size-4" />} busy={report.isFetching}
            onClick={() => report.refetch()}>Refresh report</Button>
        </header>

        {filters.warning ? <p role="alert" className="mt-5 rounded-xl border border-line-strong bg-sky-wash p-4 text-sm text-sky-ink">{filters.warning}</p> : null}

        <section aria-label="Report filters" className="mt-6 rounded-[var(--radius-card)] border border-line bg-surface p-4 md:p-5">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="w-full sm:w-56">
              <Field label="Report period">
                {({ id }) => <Select id={id} value={filters.period} disabled={navigating}
                  onChange={(event) => selectPeriod(event.target.value)}>
                  {REPORT_PERIODS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  {customOption ? <option value={filters.period}>{data?.period.label ?? "Linked period"}</option> : null}
                </Select>}
              </Field>
            </div>
            <div role="group" aria-label="Report currency" className="flex max-w-full flex-wrap gap-2">
              {currencies.map((code) => <button key={code} type="button" aria-pressed={code === currency}
                disabled={navigating} onClick={() => selectCurrency(code)}
                className={`rounded-full border px-3 py-2 text-sm font-medium transition-colors disabled:opacity-60 ${
                  code === currency ? "border-sky-deep bg-sky-wash text-sky-ink" : "border-line-strong text-ink-soft hover:bg-paper"
                }`}>{code}{code === (data?.baseCurrency ?? me.data?.profile.baseCurrency) ? <span className="sr-only"> (base currency)</span> : null}</button>)}
            </div>
          </div>
          {filters.period === "range" ? <CustomRange key={`${filters.query.start}:${filters.query.end}`}
            start={filters.query.start ?? today} end={filters.query.end ?? today}
            onApply={(start, end) => navigate(reportHref("range", filters.currency, { start, end }))} /> : null}
          {filters.period === "last_3_months" || filters.period === "last_6_months" ?
            <p className="mt-3 text-xs text-ink-faint">Includes the current month to date. Dates are saved in the link.</p> : null}
        </section>

        <div aria-busy={report.isFetching || navigating}>
          {report.isPending ? <p role="status" className="py-16 text-center text-ink-soft">Loading your report…</p>
            : report.isError ? <section role="alert" className="mt-6 rounded-[var(--radius-card)] border border-line bg-surface p-8 text-center">
              <h2 className="display text-lg font-semibold">Couldn&apos;t load this report</h2>
              <p className="mt-2 text-sm text-ink-soft">{report.error.message}</p>
              <Button className="mt-4" onClick={() => report.refetch()}>Try again</Button>
            </section> : data ? <>
              <div className="mt-6 flex flex-wrap items-end justify-between gap-2">
                <div>
                  <h2 className="text-base font-semibold">{periodLabel(data.period, locale)} <span className="text-sm font-normal text-ink-faint">(inclusive)</span></h2>
                  <p className="mt-1 text-sm text-ink-soft">Compared with {periodLabel(data.comparisonPeriod, locale)}</p>
                </div>
                <p className="text-sm text-ink-faint">{data.transactionCount.toLocaleString(locale)} {data.transactionCount === 1 ? "transaction" : "transactions"} across all currencies</p>
              </div>
              {data.transactionCount === 0 ? <EmptyReport /> : selected ? <>
                <p className="mt-5 text-sm font-medium text-ink-soft">Showing {currency} · amounts are never converted or combined</p>
                <div className="mt-3 grid gap-4 lg:grid-cols-3">
                  <MetricCard label="Spent" metric={selected.expense} locale={locale} icon={<ArrowUpRight aria-hidden className="size-4" />}
                    note={`Expenses in ${currency}`} noPrevious="No previous spending" />
                  <MetricCard label="Received" metric={selected.income} locale={locale} icon={<ArrowDownLeft aria-hidden className="size-4" />}
                    note={`Income in ${currency}`} noPrevious="No previous income" />
                  <MetricCard label="Net" metric={selected.net} locale={locale} icon={<Wallet aria-hidden className="size-4" />}
                    note="Received minus spent" noPrevious="Previous net was zero" />
                </div>
                <ReportCharts key={`${currency}:${data.period.start}:${data.period.end}`} report={selected} period={data.period} locale={locale} />
              </> : <EmptyReport currency={currency} />}
              <footer className="mt-6 border-t border-line pt-4 text-xs leading-relaxed text-ink-faint">
                <p>{data.dataSource}. Transfers and deleted transactions are excluded; shared expenses include your own share.</p>
                <p className="mt-1">Dates use your profile timezone ({me.data?.profile.timezone}). Base currency: {data.baseCurrency}.</p>
              </footer>
            </> : null}
        </div>
      </div>
    </div>
  );
}
