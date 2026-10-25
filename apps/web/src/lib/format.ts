/** Display helpers. Amounts from the API arrive pre-formatted; these cover dates and inputs. */

const MS_PER_DAY = 86_400_000;

function parseISODate(value: string): Date {
  const [year, month, day] = value.split("-").map(Number);
  return new Date(year, month - 1, day);
}

export function todayISO(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset() * 60_000;
  return new Date(now.getTime() - offset).toISOString().slice(0, 10);
}

/** "Today", "Yesterday", "Fri, 23 Oct", or "Mon, 20 Oct 2025". */
export function formatDay(isoDate: string, locale = "en-IN"): string {
  const date = parseISODate(isoDate);
  const today = parseISODate(todayISO());
  const diff = Math.round((today.getTime() - date.getTime()) / MS_PER_DAY);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  return date.toLocaleDateString(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(date.getFullYear() === today.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Relative time for lists: "just now", "12 min ago", "3 h ago", "2 Oct". */
export function formatRelative(isoDateTime: string, locale = "en-IN"): string {
  const then = new Date(isoDateTime);
  const seconds = Math.max(0, (Date.now() - then.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86_400) return `${Math.floor(seconds / 3600)} h ago`;
  return then.toLocaleDateString(locale, { day: "numeric", month: "short" });
}

export function currencySymbol(currency: string, locale = "en-IN"): string {
  try {
    const parts = new Intl.NumberFormat(locale, { style: "currency", currency }).formatToParts(0);
    return parts.find((part) => part.type === "currency")?.value ?? currency;
  } catch {
    return currency;
  }
}

export const PAYMENT_METHODS: { value: string; label: string }[] = [
  { value: "upi", label: "UPI" },
  { value: "cash", label: "Cash" },
  { value: "debit_card", label: "Debit card" },
  { value: "credit_card", label: "Credit card" },
  { value: "card", label: "Card" },
  { value: "net_banking", label: "Net banking" },
  { value: "wallet", label: "Wallet" },
  { value: "bank_transfer", label: "Bank transfer" },
  { value: "cheque", label: "Cheque" },
  { value: "other", label: "Other" },
];

export function paymentLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  return PAYMENT_METHODS.find((method) => method.value === value)?.label ?? value;
}
