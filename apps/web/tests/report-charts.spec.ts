/** Production-browser coverage for chart values, accessibility and exact drill-down URLs. */
import { expect, test, type Page } from "@playwright/test";
import type { ReportOverview } from "@moneymoney/contracts";

import { mockApp, money, overview } from "./fixtures/reports";

const FOOD = "01940000-0000-7000-8000-000000000002";

function chartReport(): ReportOverview {
  const data = overview();
  const inr = data.currencies[0];
  inr.trend = [
    { start: "2026-11-01", end: "2026-11-01", label: "1 Nov", expense: money("INR", 8000, "₹80.00"), income: money("INR", 0, "₹0.00"), net: money("INR", -8000, "-₹80.00") },
    { start: "2026-11-02", end: "2026-11-24", label: "2–24 Nov", expense: money("INR", 4345, "₹43.45"), income: money("INR", 100000, "₹1,000.00"), net: money("INR", 95655, "₹956.55") },
  ];
  inr.expenseByCategory = [
    { categoryId: FOOD, slug: "food", name: "Food & Dining", icon: "utensils", total: money("INR", 8000, "₹80.00"), count: 1, sharePercent: 64.8 },
    { categoryId: null, slug: "uncategorized", name: "Uncategorized", icon: null, total: money("INR", 4345, "₹43.45"), count: 2, sharePercent: 35.2 },
  ];
  inr.topMerchants = [
    { key: "strasse", name: "Straße", total: money("INR", 8000, "₹80.00"), count: 1, isOther: false },
    { key: "other", name: "Other merchants", total: money("INR", 4345, "₹43.45"), count: 2, isOther: true },
  ];
  return data;
}

async function expectTransactionRequest(page: Page, expected: Record<string, string>, click: () => Promise<unknown>) {
  const request = page.waitForRequest((req) => new URL(req.url()).pathname === "/api/v1/transactions");
  await click();
  const params = new URL((await request).url()).searchParams;
  for (const [key, value] of Object.entries(expected)) expect(params.get(key)).toBe(value);
  expect(params.get("q")).toBeNull();
}

test("shows every server chart value in accessible table alternatives", async ({ page }) => {
  await mockApp(page, chartReport);
  await page.setViewportSize({ width: 1440, height: 1300 });
  await page.goto("/reports");
  const trend = page.getByRole("region", { name: "Income and expense trend", exact: true });
  await expect(trend.getByRole("group", { name: /Income and expense trend chart in INR/ })).toBeVisible();
  await trend.locator("summary").click();
  const trendTable = trend.getByRole("table");
  await expect(trendTable).toContainText("₹1,000.00");
  await expect(trendTable).toContainText("₹956.55");
  await expect(trendTable).toContainText("2 Nov 2026 – 24 Nov 2026");
  await expect(trendTable.getByRole("row")).toHaveCount(3);
  const category = page.getByRole("region", { name: "Spending by category", exact: true });
  await category.locator("summary").click();
  await expect(category.getByRole("table")).toContainText("64.8%");
  await expect(category.getByRole("table")).toContainText("Uncategorized");
  const merchant = page.getByRole("region", { name: "Top merchants", exact: true });
  await merchant.locator("summary").click();
  await expect(merchant.getByRole("table")).toContainText("Other merchants");
  await page.screenshot({ path: test.info().outputPath("report-charts-desktop.png"), fullPage: true });
});

test("keyboard focus reveals exact trend values and opens only the matching series and dates", async ({ page }) => {
  await mockApp(page, chartReport);
  await page.goto("/reports");
  const point = page.getByRole("link", { name: "Received · 2 Nov 2026 – 24 Nov 2026 · ₹1,000.00. View transactions", exact: true });
  await point.focus();
  await expect(page.getByRole("status").filter({ hasText: "Received · 2 Nov" })).toContainText("₹1,000.00");
  await expectTransactionRequest(page, { type: "income", from: "2026-11-02", to: "2026-11-24", currency: "INR" }, () => page.keyboard.press("Enter"));
  await expect(page.getByLabel("Type", { exact: true })).toHaveValue("income");
  await expect(page.getByLabel("From date")).toHaveValue("2026-11-02");
  await page.reload();
  await expect(page.getByLabel("Currency", { exact: true })).toHaveValue("INR");
});

test("category, uncategorized and merchant charts open exact transaction filters", async ({ page }) => {
  await mockApp(page, chartReport);
  const base = { type: "expense", from: "2026-11-01", to: "2026-11-24", currency: "INR" };
  for (const [region, name, extra] of [
    ["Spending by category", "Food & Dining", { categoryId: FOOD }],
    ["Spending by category", "Uncategorized", { uncategorized: "true" }],
    ["Top merchants", "Straße", { merchantKey: "strasse" }],
    ["Top merchants", "Other merchants", { otherMerchants: "true" }],
  ] as const) {
    await page.goto("/reports");
    const link = page.getByRole("region", { name: region, exact: true }).getByRole("link").filter({ hasText: name }).first();
    await expectTransactionRequest(page, { ...base, ...extra }, () => link.click());
    await expect(page.getByLabel("Type", { exact: true })).toHaveValue("expense");
    await expect(page.getByLabel("Currency", { exact: true })).toHaveValue("INR");
    if ("categoryId" in extra) await expect(page.getByLabel("Category", { exact: true })).toHaveValue(FOOD);
    if ("uncategorized" in extra) await expect(page.getByLabel("Category", { exact: true })).toHaveValue("uncategorized");
    if ("otherMerchants" in extra || "merchantKey" in extra) {
      await expect(page.getByRole("button", { name: "Remove merchant filter" })).toBeVisible();
      await page.getByRole("button", { name: "Remove merchant filter" }).click();
      await expect(page.getByRole("button", { name: "Remove merchant filter" })).toHaveCount(0);
      await page.goBack();
      await expect(page.getByRole("button", { name: "Remove merchant filter" })).toBeVisible();
    }
  }
});

test("transaction search stays editable while its URL and history preserve report filters", async ({ page }) => {
  await mockApp(page, chartReport);
  await page.goto("/transactions?from=2026-11-01&to=2026-11-24&currency=INR&type=expense&merchantKey=strasse");
  const search = page.getByRole("searchbox");
  await search.pressSequentially("lunch test");
  await expect(search).toHaveValue("lunch test");
  await expect(page).toHaveURL(/q=lunch\+test/);
  await page.reload();
  await expect(search).toHaveValue("lunch test");
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page).toHaveURL("http://127.0.0.1:3100/transactions");
  await page.goBack();
  await expect(search).toHaveValue("lunch test");
  await expect(page.getByLabel("From date")).toHaveValue("2026-11-01");
});

for (const [currency, formatted] of [["JPY", "¥123"], ["KWD", "KWD 1.234"]]) {
  test(`preserves server formatting for ${currency} and handles a single all-zero point`, async ({ page }) => {
    const data = chartReport();
    const report = data.currencies[0];
    report.currency = currency;
    report.trend = [{ start: "2026-11-01", end: "2026-11-01", label: "1 Nov", expense: money(currency, 0, formatted), income: money(currency, 0, formatted), net: money(currency, 0, formatted) }];
    report.expenseByCategory = [];
    report.topMerchants = [];
    data.currencies = [report];
    await mockApp(page, () => data);
    await page.goto(`/reports?currency=${currency}`);
    const svg = page.getByRole("group", { name: new RegExp(`trend chart in ${currency}`) });
    await expect(svg.getByRole("link")).toHaveCount(2);
    const markup = await svg.innerHTML();
    expect(markup).not.toMatch(/NaN|Infinity/);
    await svg.getByRole("link").first().focus();
    await expect(page.getByRole("status").filter({ hasText: "Spent ·" })).toContainText(formatted);
    await expect(page.getByText("No category spending in this period.")).toBeVisible();
    await expect(page.getByText("No merchant spending in this period.")).toBeVisible();
  });
}

test("mobile dark charts wrap long labels and scroll only tables with reduced motion", async ({ page }) => {
  const data = chartReport();
  const longName = "VeryLongMerchantAndCategoryName".repeat(6);
  data.currencies[0].expenseByCategory[0].name = longName;
  data.currencies[0].topMerchants[0].name = longName;
  await page.setViewportSize({ width: 360, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => localStorage.setItem("mm-theme", "dark"));
  await mockApp(page, () => data);
  await page.goto("/reports");
  await expect(page.getByRole("region", { name: "Top merchants", exact: true })).toBeVisible();
  const panels = page.locator("main section");
  for (const panel of await panels.all()) {
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("region", { name: "Income and expense trend", exact: true }).screenshot({ path: test.info().outputPath("report-trend-mobile-dark.png") });
  const merchants = page.getByRole("region", { name: "Top merchants", exact: true });
  await merchants.screenshot({ path: test.info().outputPath("report-merchants-mobile-dark.png") });
  await merchants.locator("summary").click();
  await expect(merchants.getByRole("table")).toContainText(longName);
});
