/** Deterministic report and shell fixtures; browser tests never touch a real ledger. */
import type { Page } from "@playwright/test";
import type { CurrencyReport, MeView, MoneyAmount, ReportOverview } from "@moneymoney/contracts";

const profile: MeView = {
  user: { id: "01940000-0000-7000-8000-000000000001", email: "reports@example.test", displayName: "Report tester", createdAt: "2026-11-01T00:00:00Z" },
  profile: { baseCurrency: "INR", timezone: "Asia/Kolkata", locale: "en-IN" },
};

export function money(currency: string, amountMinor: number, formatted: string): MoneyAmount {
  return { currency, amountMinor, formatted, amount: "0" };
}

function currencyReport(currency: string): CurrencyReport {
  // Explicit display values prove the page consumes API formatting instead of recalculating.
  const current = money(currency, 12345, currency === "INR" ? "₹123.45" : "$123.45");
  const zero = money(currency, 0, currency === "INR" ? "₹0.00" : "$0.00");
  return {
    currency,
    expense: { current, previous: zero, change: current, changePercent: null },
    income: { current: zero, previous: zero, change: zero, changePercent: null },
    net: { current: money(currency, -12345, currency === "INR" ? "-₹123.45" : "-$123.45"), previous: zero, change: money(currency, -12345, currency === "INR" ? "-₹123.45" : "-$123.45"), changePercent: null },
    expenseByCategory: [], topMerchants: [], trend: [], insights: [],
  };
}

export function overview(): ReportOverview {
  return {
    period: { start: "2026-11-01", end: "2026-11-24", label: "November 2026" },
    comparisonPeriod: { start: "2026-10-08", end: "2026-10-31", label: "Previous 24 days" },
    bucketKind: "day", baseCurrency: "INR", transactionCount: 3,
    generatedAt: "2026-11-24T06:00:00Z", dataSource: "Transactions recorded in MoneyMoney",
    currencies: [currencyReport("INR"), currencyReport("USD")],
  };
}

/** All unrelated shell endpoints are stubbed too, so tests never read or mutate a real ledger. */
export async function mockApp(page: Page, getReport: () => ReportOverview = overview) {
  await page.context().addCookies([{ name: "mm_session", value: "browser-test", url: "http://127.0.0.1:3100" }]);
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const bodies: Record<string, unknown> = {
      "/api/v1/me": profile,
      "/api/v1/conversations": { items: [], nextCursor: null },
      "/api/v1/notices": { items: [], unreadCount: 0 },
      "/api/v1/transactions": { items: [], nextCursor: null },
      "/api/v1/categories": [], "/api/v1/accounts": [], "/api/v1/friends": [],
    };
    if (path === "/api/v1/reports/overview") {
      await route.fulfill({ json: getReport() });
    } else if (path in bodies) {
      await route.fulfill({ json: bodies[path] });
    } else {
      throw new Error(`Unexpected test request: ${route.request().method()} ${path}`);
    }
  });
}

