"use client";

import type { ReportInteraction } from "@moneymoney/contracts";
import Link from "next/link";

import { TrendChart } from "@/components/reports/report-charts";
import { reportHref } from "@/lib/report-filters";
import { reportPeriodLabel, reportTransactionsHref } from "@/lib/report-links";
import { useMe } from "@/lib/queries";

/** A saved, versioned report snapshot; opening Reports reads the current ledger again. */
export function ReportCard({ interaction }: { interaction: ReportInteraction }) {
  const locale = useMe().data?.profile.locale ?? "en-IN";
  if (interaction.version !== 1) return null;
  const report = interaction.preview;
  const title = { trend: "Spending trend", breakdown: "Spending breakdown", insights: "Spending insights" }[interaction.kind];
  return (
    <section aria-label={`Chat ${title.toLowerCase()}`} className="mt-2 min-w-0 overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <div className="border-b border-line px-4 py-3">
        <h3 className="display text-base font-semibold">{title} · {interaction.currency}</h3>
        <p className="mt-1 text-xs text-ink-soft">{reportPeriodLabel(interaction.period, locale)} (inclusive)</p>
        <p className="mt-1 text-xs text-ink-faint">Saved report snapshot · {interaction.transactionCount} transactions across all currencies</p>
      </div>
      <div className="space-y-4 p-4">
        {report ? <>
          <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            {[["Spent", report.expense.current.formatted], ["Received", report.income.current.formatted], ["Net", report.net.current.formatted]].map(([label, value]) =>
              <div key={label} className="min-w-0 rounded-lg bg-paper p-3"><dt className="text-xs text-ink-faint">{label}</dt><dd className="figure mt-1 text-lg font-semibold break-words">{value}</dd></div>)}
          </dl>
          {interaction.kind === "trend" ? <TrendChart report={report} locale={locale} /> : null}
          {interaction.kind === "breakdown" ? <>
            <h4 className="text-sm font-semibold">Top categories (up to five)</h4>
            <ul className="space-y-2 text-sm">{report.expenseByCategory.map((item) => <li key={item.categoryId ?? "uncategorized"}>
              <Link className="flex items-start justify-between gap-3 rounded-lg px-2 py-1 text-sky-deep hover:bg-paper" href={reportTransactionsHref(interaction.period, interaction.currency, { type: "expense", ...(item.categoryId ? { categoryId: item.categoryId } : { uncategorized: "true" }) })}>
                <span className="min-w-0 [overflow-wrap:anywhere]">{item.name} · {item.sharePercent.toLocaleString(locale)}%</span><span className="figure shrink-0">{item.total.formatted}</span>
              </Link>
            </li>)}</ul>
            <h4 className="text-sm font-semibold">Merchant preview (up to three groups)</h4>
            <ul className="space-y-2 text-sm">{report.topMerchants.map((item) => <li key={`${item.isOther}:${item.key}`}>
              <Link className="flex items-start justify-between gap-3 rounded-lg px-2 py-1 text-sky-deep hover:bg-paper" href={reportTransactionsHref(interaction.period, interaction.currency, { type: "expense", ...(item.isOther ? { otherMerchants: "true" } : { merchantKey: item.key }) })}>
                <span className="min-w-0 [overflow-wrap:anywhere]">{item.name}</span><span className="figure shrink-0">{item.total.formatted}</span>
              </Link>
            </li>)}</ul>
            {report.expenseByCategory.length === 0 ? <p className="text-sm text-ink-soft">No expense breakdown in this currency and period.</p> : null}
          </> : null}
          {interaction.kind === "insights" ? <ul className="space-y-3 text-sm text-ink-soft">
            {report.insights.map((item) => <li key={item.kind}>{item.text}</li>)}
            {report.insights.length === 0 ? <li>No spending insights in this currency and period.</li> : null}
          </ul> : null}
        </> : <p className="text-sm text-ink-soft">No {interaction.currency} transactions in this period. Choose another currency in the full report, or add a transaction.</p>}
        <p className="text-xs text-ink-faint">Currencies are kept separate. This snapshot is from {new Date(interaction.generatedAt).toLocaleString(locale)}.</p>
        {interaction.availableCurrencies.length > 1 ? <div aria-label="Other report currencies" className="flex flex-wrap gap-2 text-sm">
          {interaction.availableCurrencies.filter((code) => code !== interaction.currency).map((code) => <Link key={code} href={reportHref("range", code, { start: interaction.period.start, end: interaction.period.end })} className="rounded-full border border-line-strong px-3 py-1 text-sky-deep">View {code} report</Link>)}
        </div> : null}
      </div>
      <Link href={interaction.reportHref} className="block border-t border-line px-4 py-3 text-sm font-medium text-sky-deep hover:bg-sky-wash">Open full report</Link>
    </section>
  );
}
