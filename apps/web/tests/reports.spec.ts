/** Browser-level report contracts: URL/history, currency isolation, states and ledger refresh. */
import { expect, test, type Page } from "@playwright/test";
import type { CurrencyReport, MeView, MoneyAmount, ReportOverview } from "@moneymoney/contracts";

import { readReportFilters, reportMonthRange, reportRangeError, reportToday } from "../src/lib/report-filters";

const profile: MeView = {
  user: { id: "01940000-0000-7000-8000-000000000001", email: "reports@example.test", displayName: "Report tester", createdAt: "2026-11-01T00:00:00Z" },
  profile: { baseCurrency: "INR", timezone: "Asia/Kolkata", locale: "en-IN" },
};

function money(currency: string, amountMinor: number, formatted: string): MoneyAmount {
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
    expenseByCategory: [], topMerchants: [], trend: [],
  };
}

function overview(): ReportOverview {
  return {
    period: { start: "2026-11-01", end: "2026-11-24", label: "November 2026" },
    comparisonPeriod: { start: "2026-10-08", end: "2026-10-31", label: "Previous 24 days" },
    bucketKind: "day", baseCurrency: "INR", transactionCount: 3,
    generatedAt: "2026-11-24T06:00:00Z", dataSource: "Transactions recorded in MoneyMoney",
    currencies: [currencyReport("INR"), currencyReport("USD")],
  };
}

/** All unrelated shell endpoints are stubbed too, so tests never read or mutate a real ledger. */
async function mockApp(page: Page, getReport: () => ReportOverview = overview) {
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

test("restores exact dates and currency on reload and history navigation", async ({ page }) => {
  await mockApp(page);
  const request = page.waitForRequest((req) => req.url().includes("/reports/overview?"));
  await page.goto("/reports?period=range&start=2026-11-01&end=2026-11-24&currency=USD");
  const url = new URL((await request).url());
  expect(url.searchParams.get("start")).toBe("2026-11-01");
  expect(url.searchParams.get("end")).toBe("2026-11-24");
  await expect(page.getByLabel("Report period")).toHaveValue("range");
  await expect(page.getByLabel("Start date")).toHaveValue("2026-11-01");
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toContainText("$123.45");
  await expect(page.getByRole("region", { name: "Spent", exact: true })).not.toContainText("₹");
  await expect(page.getByRole("group", { name: "Report currency" }).getByRole("button").first()).toHaveText("INR (base currency)");
  await page.getByRole("button", { name: "INR (base currency)" }).click();
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toContainText("₹123.45");
  await page.goBack();
  await expect(page.getByRole("button", { name: "USD", exact: true })).toHaveAttribute("aria-pressed", "true");
  await page.reload();
  await expect(page.getByLabel("End date")).toHaveValue("2026-11-24");
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toContainText("$123.45");
  await expect(page.getByText("No previous spending")).toBeVisible();
  await expect(page.getByText("Compared with 8 Oct 2026 – 31 Oct 2026")).toBeVisible();
});

test("validates custom dates without changing the active report, then applies a valid range", async ({ page }) => {
  await mockApp(page);
  await page.goto("/reports?period=range&start=2026-11-01&end=2026-11-24");
  await page.getByLabel("Start date").fill("2026-11-25");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("The end date must be on or after the start date.");
  expect(page.url()).toContain("start=2026-11-01");
  await page.getByLabel("Start date").fill("2020-01-01");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("at most 5 years");
  await page.getByLabel("Start date").fill("2026-10-01");
  await page.getByRole("button", { name: "Apply dates" }).click();
  await expect(page).toHaveURL(/start=2026-10-01/);
  await page.reload();
  await expect(page.getByLabel("Start date")).toHaveValue("2026-10-01");
});

test("pins multi-month preset dates and visibly falls back for invalid links", async ({ page }) => {
  await mockApp(page);
  await page.goto("/reports?period=range&start=2026-02-30&end=2026-03-05");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Showing this month instead");
  await expect(page.getByLabel("Report period")).toHaveValue("this_month");
  await page.getByLabel("Report period").selectOption("last_3_months");
  await expect(page).toHaveURL(/period=last_3_months&start=\d{4}-\d{2}-01&end=/);
  const pinned = page.url();
  await page.reload();
  await expect(page).toHaveURL(pinned);
  await expect(page.getByLabel("Report period")).toHaveValue("last_3_months");
});

test("offers separate empty states for the whole period and a missing selected currency", async ({ page }) => {
  let data = overview();
  await mockApp(page, () => data);
  await page.goto("/reports?currency=EUR");
  await expect(page.getByRole("heading", { name: "No EUR transactions in this period" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Add or import transactions" })).toHaveAttribute("href", "/transactions");
  data = { ...data, currencies: [], transactionCount: 0 };
  await page.getByRole("button", { name: "Refresh report" }).click();
  await expect(page.getByRole("heading", { name: "A fresh page for your money" })).toBeVisible();
});

test("keeps base currency first when only a foreign currency has data", async ({ page }) => {
  const data = { ...overview(), currencies: [currencyReport("USD")] };
  await mockApp(page, () => data);
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "No INR transactions in this period" })).toBeVisible();
  await page.getByRole("button", { name: "USD", exact: true }).click();
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toContainText("$123.45");
});

test("announces loading and offers retry after an API error", async ({ page }) => {
  await mockApp(page);
  let finish: (() => void) | undefined;
  const pending = new Promise<void>((resolve) => { finish = resolve; });
  let fail = true;
  await page.route("**/api/v1/reports/overview**", async (route) => {
    await pending;
    await route.fulfill(fail
      ? { status: 400, json: { error: { code: "invalid_period", message: "Please choose a shorter report period." } } }
      : { json: overview() });
  });
  await page.goto("/reports");
  await expect(page.getByRole("status").filter({ hasText: "Loading your report" })).toBeVisible();
  finish!();
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Please choose a shorter report period.");
  fail = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toBeVisible();
});

test("refreshes a cached report after saving a transaction and revisiting the page", async ({ page }) => {
  let data = overview();
  await mockApp(page, () => data);
  await page.route("**/api/v1/transactions", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    data = overview();
    data.currencies[0].expense.current = money("INR", 99900, "₹999.00");
    await route.fulfill({ status: 201, json: {} });
  });
  await page.goto("/reports");
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toContainText("₹123.45");
  await page.getByRole("link", { name: "Transactions", exact: true }).click();
  await page.getByRole("button", { name: "Add transaction", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Amount", { exact: true }).fill("10");
  await dialog.getByRole("button", { name: "Add transaction", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toContainText("₹999.00");
});

test("uses the mobile navigation and dark palette without horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => localStorage.setItem("mm-theme", "dark"));
  await mockApp(page);
  await page.goto("/transactions");
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--color-paper").trim())).toBe("#0a0c0f");
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(360);
  const usd = page.getByRole("button", { name: "USD", exact: true });
  await usd.focus();
  await page.keyboard.press("Enter");
  await expect(usd).toHaveAttribute("aria-pressed", "true");
  await page.screenshot({ path: test.info().outputPath("reports-mobile-dark.png"), fullPage: true });
});

test("redirects a signed-out report link while preserving all filters", async ({ page }) => {
  await page.goto("/reports?period=range&start=2026-11-01&end=2026-11-24&currency=USD");
  await expect(page).toHaveURL(/\/login\?next=/);
  expect(new URL(page.url()).searchParams.get("next")).toBe("/reports?period=range&start=2026-11-01&end=2026-11-24&currency=USD");
});

test("preserves the report link when a session has expired", async ({ page }) => {
  await mockApp(page);
  await page.route("**/api/v1/me", (route) => route.fulfill({ status: 401, json: { error: { code: "unauthenticated", message: "Please sign in." } } }));
  await page.goto("/reports?period=last_year&currency=USD");
  await expect(page).toHaveURL(/\/login\?next=/);
  expect(new URL(page.url()).searchParams.get("next")).toBe("/reports?period=last_year&currency=USD");
});

test("shows exact values and accessible navigation in the desktop light theme", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.addInitScript(() => localStorage.setItem("mm-theme", "light"));
  await mockApp(page);
  await page.goto("/reports");
  await expect(page.getByRole("link", { name: "Reports", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("region", { name: "Net", exact: true })).toContainText("-₹123.45");
  await expect(page.getByText("3 transactions across all currencies")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({ path: test.info().outputPath("reports-desktop-light.png"), fullPage: true });
});

test("calendar filters handle timezone boundaries, leap days, caps and malformed parameters", () => {
  expect(reportToday("Asia/Kolkata", new Date("2026-12-31T20:00:00Z"))).toBe("2027-01-01");
  expect(reportToday("America/Los_Angeles", new Date("2026-01-01T01:00:00Z"))).toBe("2025-12-31");
  expect(reportMonthRange("2026-01-31", 3)).toEqual({ start: "2025-11-01", end: "2026-01-31" });
  expect(reportMonthRange("2026-03-01", 6)).toEqual({ start: "2025-10-01", end: "2026-03-01" });
  expect(reportRangeError("2024-02-29", "2024-02-29")).toBeNull();
  expect(reportRangeError("2026-02-29", "2026-03-01")).toContain("valid");
  expect(reportRangeError("2020-01-01", "2025-01-03")).toBeNull();
  expect(reportRangeError("2020-01-01", "2025-01-04")).toContain("at most");
  for (const query of ["period=unknown", "period=range", "period=month&month=2026-13", "period=last_n_days&days=1831", "period=this_year&period=last_year"]) {
    const filters = readReportFilters(new URLSearchParams(query), "2026-11-24");
    expect(filters.warning).toContain("Showing this month instead");
    expect(filters.query).toEqual({ period: "this_month" });
  }
});
