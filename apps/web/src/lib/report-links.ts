/** Exact, same-origin transaction destinations for report rows and chart points. */
import type { PeriodView } from "@moneymoney/contracts";

export function reportTransactionsHref(
  period: Pick<PeriodView, "start" | "end">,
  currency: string,
  filters: { type: "expense" | "income"; categoryId?: string; uncategorized?: string; merchantKey?: string; otherMerchants?: string },
) {
  return `/transactions?${new URLSearchParams({ from: period.start, to: period.end, currency, ...filters })}`;
}

export function reportPeriodLabel(period: Pick<PeriodView, "start" | "end">, locale: string) {
  const label = (day: string) => new Date(`${day}T00:00:00Z`).toLocaleDateString(locale, {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
  return period.start === period.end ? label(period.start) : `${label(period.start)} – ${label(period.end)}`;
}
