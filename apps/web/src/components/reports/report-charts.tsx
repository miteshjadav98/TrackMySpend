"use client";

import type { CurrencyReport, MoneyAmount, PeriodView } from "@moneymoney/contracts";
import Link from "next/link";
import { type ReactNode, useId, useState } from "react";

import { NamedIcon } from "@/components/ui/icons";
import { reportPeriodLabel, reportTransactionsHref } from "@/lib/report-links";

const CELL = "border-t border-line px-3 py-3 align-top";
const HEADING = "px-3 py-3 text-left text-xs font-semibold text-ink-soft";
const LINK = "rounded text-sky-deep underline decoration-sky/50 underline-offset-4 hover:decoration-sky-deep";

/** Geometry only: totals, percentages, grouping and money formatting remain server-owned. */
function proportion(value: number, maximum: number): number {
  if (!Number.isFinite(value) || !Number.isFinite(maximum) || maximum <= 0) return 0;
  return Math.min(1, Math.max(0, value / maximum));
}

function ChartPanel({ title, description, children, table }: {
  title: string; description: string; children: ReactNode; table: ReactNode;
}) {
  const id = useId();
  return (
    <section aria-labelledby={id} className="min-w-0 rounded-[var(--radius-card)] border border-line bg-surface p-4 shadow-[var(--shadow-card)] md:p-5">
      <h2 id={id} className="display text-lg font-semibold">{title}</h2>
      <p className="mt-1 text-sm text-ink-soft">{description}</p>
      {children}
      <details className="mt-5 border-t border-line pt-3">
        <summary className="cursor-pointer rounded py-1 text-sm font-medium text-sky-deep">View {title.toLowerCase()} data table</summary>
        <div tabIndex={0} role="region" aria-label={`${title} data table, scroll horizontally if needed`}
          className="mt-3 max-w-full overflow-x-auto rounded-lg border border-line">{table}</div>
      </details>
    </section>
  );
}

function TrendChart({ report, locale }: { report: CurrencyReport; locale: string }) {
  const id = useId();
  const [focused, setFocused] = useState<string | null>(null);
  const points = report.trend;
  const amounts = points.flatMap((point) => [point.expense, point.income]);
  const maximum = amounts.reduce<MoneyAmount | null>((best, item) =>
    !best || item.amountMinor > best.amountMinor ? item : best, null);
  const x = (index: number) => points.length === 1 ? 360 : 16 + index * 688 / (points.length - 1);
  const y = (value: number) => 204 - proportion(value, maximum?.amountMinor ?? 0) * 184;
  const line = (series: "expense" | "income") => points.map((point, index) => `${x(index)},${y(point[series].amountMinor)}`).join(" ");

  return (
    <ChartPanel title="Income and expense trend" description={`Exact ${report.currency} amounts. Select a point or table value to inspect its transactions.`}
      table={<table className="w-full text-sm">
        <caption className="sr-only">Income and expense trend in {report.currency}</caption>
        <thead><tr>{["Inclusive dates", "Spent", "Received", "Net"].map((heading) => <th key={heading} scope="col" className={HEADING}>{heading}</th>)}</tr></thead>
        <tbody>{points.map((point) => <tr key={point.start}>
          <th scope="row" className={`${CELL} min-w-40 text-left font-normal`}>{reportPeriodLabel(point, locale)}</th>
          <td className={`${CELL} figure whitespace-nowrap`}><Link className={LINK} href={reportTransactionsHref(point, report.currency, { type: "expense" })}>{point.expense.formatted}</Link></td>
          <td className={`${CELL} figure whitespace-nowrap`}><Link className={LINK} href={reportTransactionsHref(point, report.currency, { type: "income" })}>{point.income.formatted}</Link></td>
          <td className={`${CELL} figure whitespace-nowrap`}>{point.net.formatted}</td>
        </tr>)}</tbody>
      </table>}>
      {points.length ? <>
        <div className="mt-5 flex flex-wrap justify-between gap-2 text-xs text-ink-soft">
          <div className="flex flex-wrap gap-4">
            <span>● Spent · solid line</span><span className="text-sky-deep">■ Received · dashed line</span>
          </div>
          <span>Scale starts at zero · highest value {maximum?.formatted}</span>
        </div>
        <svg viewBox="0 0 720 230" role="group" aria-labelledby={`${id}-title ${id}-desc`}
          className="mt-3 block w-full overflow-visible">
          <title id={`${id}-title`}>Income and expense trend chart in {report.currency}</title>
          <desc id={`${id}-desc`}>Circles and a solid line show spent amounts; squares and a dashed line show received amounts. Focus or hover a point for its exact value, or use the data table.</desc>
          {[20, 112, 204].map((height) => <line key={height} x1="16" y1={height} x2="704" y2={height} className="stroke-line" strokeDasharray={height === 204 ? undefined : "3 5"} />)}
          <polyline points={line("expense")} fill="none" className="stroke-ink" strokeWidth="2" vectorEffect="non-scaling-stroke" />
          <polyline points={line("income")} fill="none" className="stroke-sky-deep" strokeWidth="2" strokeDasharray="6 5" vectorEffect="non-scaling-stroke" />
          {points.map((point, index) => (["expense", "income"] as const).map((series) => {
            const text = `${series === "expense" ? "Spent" : "Received"} · ${reportPeriodLabel(point, locale)} · ${point[series].formatted}`;
            return <a key={`${point.start}:${series}`} href={reportTransactionsHref(point, report.currency, { type: series })}
              aria-label={`${text}. View transactions`} onFocus={() => setFocused(text)} onMouseEnter={() => setFocused(text)}
              onBlur={() => setFocused(null)} onMouseLeave={() => setFocused(null)}>
              <title>{text}</title>
              {series === "expense" ? <circle cx={x(index)} cy={y(point[series].amountMinor)} r="5" className="fill-surface stroke-ink" strokeWidth="2" />
                : <rect x={x(index) - 4} y={y(point[series].amountMinor) - 4} width="8" height="8" className="fill-sky-deep stroke-surface" strokeWidth="1" />}
            </a>;
          }))}
        </svg>
        <div className="flex justify-between gap-3 text-xs text-ink-faint">
          <span>{reportPeriodLabel({ start: points[0].start, end: points[0].start }, locale)}</span>
          <span>{reportPeriodLabel({ start: points.at(-1)!.end, end: points.at(-1)!.end }, locale)}</span>
        </div>
        <p role="status" aria-live="polite" className="mt-3 min-h-10 rounded-lg bg-paper px-3 py-2 text-sm text-ink-soft">{focused ?? "Focus or hover a chart point for the exact dates and amount."}</p>
      </> : <p className="mt-5 text-sm text-ink-faint">No trend data in this period.</p>}
    </ChartPanel>
  );
}

function CategoryChart({ report, period, locale }: { report: CurrencyReport; period: PeriodView; locale: string }) {
  const href = (index: number) => {
    const category = report.expenseByCategory[index];
    return reportTransactionsHref(period, report.currency, { type: "expense",
      ...(category.categoryId ? { categoryId: category.categoryId } : { uncategorized: "true" }) });
  };
  return (
    <ChartPanel title="Spending by category" description={`Every expense category in ${report.currency}. Bars show the server's share of spending.`}
      table={<table className="w-full text-sm">
        <caption className="sr-only">Spending by category in {report.currency}</caption>
        <thead><tr>{["Category", "Spent", "Share", "Transactions"].map((heading) => <th key={heading} scope="col" className={HEADING}>{heading}</th>)}</tr></thead>
        <tbody>{report.expenseByCategory.map((category, index) => <tr key={category.categoryId ?? "uncategorized"}>
          <th scope="row" className={`${CELL} min-w-32 text-left font-normal [overflow-wrap:anywhere]`}><Link className={LINK} href={href(index)}>{category.name}</Link></th>
          <td className={`${CELL} figure whitespace-nowrap`}>{category.total.formatted}</td>
          <td className={`${CELL} figure`}>{category.sharePercent.toLocaleString(locale)}%</td>
          <td className={`${CELL} figure`}>{category.count.toLocaleString(locale)}</td>
        </tr>)}</tbody>
      </table>}>
      {report.expenseByCategory.length ? <ol aria-label={`Spending by category chart in ${report.currency}`} className="mt-5 space-y-4">
        {report.expenseByCategory.map((category, index) => <li key={category.categoryId ?? "uncategorized"}>
          <Link href={href(index)} className="group block rounded-lg p-1 hover:bg-paper">
            <div className="flex items-start justify-between gap-3 text-sm">
              <span className="min-w-0 [overflow-wrap:anywhere]"><span className="mr-2 text-xs text-ink-faint">{index + 1}.</span><NamedIcon name={category.icon} className="mr-2 inline size-4 text-sky-deep" />{category.name}</span>
              <span className="figure shrink-0 font-semibold">{category.total.formatted}</span>
            </div>
            <div aria-hidden className="mt-2 h-2 rounded-full bg-paper"><div className="h-full rounded-full bg-sky-fill" style={{ width: `${proportion(category.sharePercent, 100) * 100}%` }} /></div>
            <p className="mt-1 text-xs text-ink-faint">{category.sharePercent.toLocaleString(locale)}% · {category.count.toLocaleString(locale)} {category.count === 1 ? "transaction" : "transactions"}</p>
          </Link>
        </li>)}
      </ol> : <p className="mt-5 text-sm text-ink-faint">No category spending in this period.</p>}
    </ChartPanel>
  );
}

function MerchantChart({ report, period, locale }: { report: CurrencyReport; period: PeriodView; locale: string }) {
  const maximum = Math.max(0, ...report.topMerchants.map((merchant) => merchant.total.amountMinor));
  const href = (index: number) => {
    const merchant = report.topMerchants[index];
    return reportTransactionsHref(period, report.currency, { type: "expense",
      ...(merchant.isOther ? { otherMerchants: "true" } : { merchantKey: merchant.key }) });
  };
  return (
    <ChartPanel title="Top merchants" description={`Top ten in ${report.currency}, plus remaining and unnamed merchants. Bars are relative to the largest amount.`}
      table={<table className="w-full text-sm">
        <caption className="sr-only">Top merchants in {report.currency}</caption>
        <thead><tr>{["Merchant", "Spent", "Transactions"].map((heading) => <th key={heading} scope="col" className={HEADING}>{heading}</th>)}</tr></thead>
        <tbody>{report.topMerchants.map((merchant, index) => <tr key={`${merchant.isOther}:${merchant.key}`}>
          <th scope="row" className={`${CELL} min-w-32 text-left font-normal [overflow-wrap:anywhere]`}><Link className={LINK} href={href(index)}>{merchant.name}</Link></th>
          <td className={`${CELL} figure whitespace-nowrap`}>{merchant.total.formatted}</td>
          <td className={`${CELL} figure`}>{merchant.count.toLocaleString(locale)}</td>
        </tr>)}</tbody>
      </table>}>
      {report.topMerchants.length ? <ol aria-label={`Top merchants chart in ${report.currency}`} className="mt-5 space-y-4">
        {report.topMerchants.map((merchant, index) => <li key={`${merchant.isOther}:${merchant.key}`}>
          <Link href={href(index)} className="group block rounded-lg p-1 hover:bg-paper">
            <div className="flex items-start justify-between gap-3 text-sm">
              <span className="min-w-0 [overflow-wrap:anywhere]"><span className="mr-2 text-xs text-ink-faint">{merchant.isOther ? "+" : `${index + 1}.`}</span>{merchant.name}</span>
              <span className="figure shrink-0 font-semibold">{merchant.total.formatted}</span>
            </div>
            <div aria-hidden className="mt-2 h-2 rounded-full bg-paper"><div className={`h-full rounded-full ${merchant.isOther ? "bg-ink-faint" : "bg-sky-fill"}`} style={{ width: `${proportion(merchant.total.amountMinor, maximum) * 100}%` }} /></div>
            <p className="mt-1 text-xs text-ink-faint">{merchant.count.toLocaleString(locale)} {merchant.count === 1 ? "transaction" : "transactions"}</p>
          </Link>
        </li>)}
      </ol> : <p className="mt-5 text-sm text-ink-faint">No merchant spending in this period.</p>}
    </ChartPanel>
  );
}

/** One currency's bounded report data, shown as charts and exact accessible tables. */
export function ReportCharts({ report, period, locale }: { report: CurrencyReport; period: PeriodView; locale: string }) {
  return (
    <div className="mt-6 space-y-4">
      <TrendChart report={report} locale={locale} />
      <div className="grid items-start gap-4 xl:grid-cols-2">
        <CategoryChart report={report} period={period} locale={locale} />
        <MerchantChart report={report} period={period} locale={locale} />
      </div>
    </div>
  );
}
