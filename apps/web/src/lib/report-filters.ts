/** URL filters for reports. Calendar math uses dates in the profile's timezone, never money. */
import type { paths } from "@moneymoney/contracts";

export type ReportQuery = NonNullable<
  paths["/api/v1/reports/overview"]["get"]["parameters"]["query"]
>;

export const REPORT_PERIODS = [
  ["this_month", "This month"],
  ["last_month", "Last month"],
  ["last_3_months", "Last 3 months"],
  ["last_6_months", "Last 6 months"],
  ["this_year", "This year"],
  ["last_year", "Last year"],
  ["range", "Custom range"],
] as const;

const SIMPLE_PERIODS = new Set([
  "today", "yesterday", "this_week", "last_week", "this_month", "last_month",
  "this_year", "last_year",
]);
const MS_PER_DAY = 86_400_000;
export const EARLIEST_REPORT_DATE = "1990-01-01";

/** ISO calendar day at an instant in the user's profile timezone, independent of the browser. */
export function reportToday(timezone: string, now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)!.value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}

function validDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/** Same inclusive 1,830-day cap as the API; reject impossible dates before requesting data. */
export function reportRangeError(start: string, end: string): string | null {
  if (!validDate(start) || !validDate(end)) return "Enter a valid start and end date.";
  if (start < EARLIEST_REPORT_DATE) return "Choose a start date on or after 1 January 1990.";
  if (end < start) return "The end date must be on or after the start date.";
  const days = (Date.parse(end) - Date.parse(start)) / MS_PER_DAY + 1;
  return days > 1830 ? "A custom range can cover at most 5 years (1,830 days)." : null;
}

/** Current month to date plus the preceding two/five calendar months, with pinned dates. */
export function reportMonthRange(today: string, months: 3 | 6): { start: string; end: string } {
  const date = new Date(`${today}T00:00:00Z`);
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() - months + 1);
  return { start: date.toISOString().slice(0, 10), end: today };
}

/** Invalid links visibly fall back to this month. Valid links preserve their selected currency. */
export function readReportFilters(params: Pick<URLSearchParams, "get" | "getAll">, today: string) {
  let period = params.get("period") ?? "this_month";
  let warning: string | null = null;
  let query: ReportQuery = { period: "this_month" };
  const start = params.get("start") ?? "";
  const end = params.get("end") ?? "";
  const rawCurrency = params.get("currency");
  const currency = rawCurrency && /^[A-Z]{3}$/.test(rawCurrency) ? rawCurrency : null;
  const duplicated = ["period", "start", "end", "month", "days", "currency"]
    .some((key) => params.getAll(key).length > 1);

  if (duplicated) {
    warning = "This link repeats a report filter. Showing this month instead.";
  } else if (SIMPLE_PERIODS.has(period)) {
    query = { period: period as ReportQuery["period"] };
  } else if (period === "range" || period === "last_3_months" || period === "last_6_months") {
    const range = period === "range" || start || end
      ? { start, end }
      : reportMonthRange(today, period === "last_3_months" ? 3 : 6);
    const error = reportRangeError(range.start, range.end);
    if (error) warning = `${error} Showing this month instead.`;
    else query = { period: "range", ...range };
  } else if (period === "month") {
    const month = params.get("month") ?? "";
    if (/^\d{4}-(0[1-9]|1[0-2])$/.test(month) && month >= "1990-01") query = { period, month };
    else warning = "This link has an invalid month. Showing this month instead.";
  } else if (period === "last_n_days") {
    const days = params.get("days") ?? "30";
    if (/^\d{1,4}$/.test(days) && Number(days) >= 1 && Number(days) <= 1830) {
      query = { period, days: Number(days) };
    } else warning = "Choose between 1 and 1,830 days. Showing this month instead.";
  } else {
    warning = "This link has an unknown period. Showing this month instead.";
  }
  if (warning) period = "this_month";
  if (rawCurrency !== null && !currency) {
    warning = [warning, "The currency filter is invalid; showing your default currency."].filter(Boolean).join(" ");
  }
  return { period, query, currency, warning };
}

/** Fixed same-origin destination; all user-controlled values are query parameters. */
export function reportHref(period: string, currency: string | null, extra: Record<string, string> = {}) {
  const params = new URLSearchParams({ period, ...extra });
  if (currency) params.set("currency", currency);
  return `/reports?${params.toString()}`;
}
