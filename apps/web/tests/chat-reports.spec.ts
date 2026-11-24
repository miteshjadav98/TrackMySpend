/** Persisted chat reports use the same trusted values and links as the full report. */
import { expect, test, type Page } from "@playwright/test";
import type { ConversationDetail, ReportInteraction } from "@moneymoney/contracts";
import { mockApp, overview } from "./fixtures/reports";

const ID = "01940000-0000-7000-8000-000000000010";
function reportCard(kind: ReportInteraction["kind"]): ReportInteraction {
  const data = overview();
  const preview = data.currencies[0];
  preview.trend = [{ start: data.period.start, end: data.period.end, label: "November", expense: preview.expense.current, income: preview.income.current, net: preview.net.current }];
  preview.expenseByCategory = [{ categoryId: null, slug: "uncategorized", name: "Uncategorized", icon: null, total: preview.expense.current, count: 3, sharePercent: 100 }];
  preview.topMerchants = [{ key: "strasse", name: "Straße", total: preview.expense.current, count: 3, isOther: false }];
  preview.insights = [{ kind: "spending_change", currency: "INR", period: data.period, text: "INR spending is ₹123.45; no previous spending.", current: preview.expense.current, previous: preview.expense.previous, change: preview.expense.change, changePercent: null, sharePercent: null, categoryId: null, merchantKey: null }];
  return { type: "report", id: "report-fixture", version: 1, kind, period: data.period, comparisonPeriod: data.comparisonPeriod, currency: "INR", availableCurrencies: ["INR", "USD"], preview, transactionCount: 3, generatedAt: data.generatedAt, reportHref: "/reports?period=range&start=2026-11-01&end=2026-11-24&currency=INR" };
}
async function chat(page: Page, card: ReportInteraction) {
  const data = overview();
  const summary = { period: data.period, baseCurrency: "INR", currencies: [], transactionCount: 0, generatedAt: data.generatedAt, dataSource: data.dataSource };
  const detail: ConversationDetail = {
    conversation: { id: ID, title: "Reports", status: "active", createdAt: data.generatedAt, lastMessageAt: data.generatedAt },
    messages: [{ id: ID, role: "assistant", content: "Your requested report.", ui: [{ type: "summary", id: "old-summary", summary }, card], status: "completed", replyToId: null, clientMessageId: null, createdAt: data.generatedAt }],
    hasMoreMessages: false, pendingInteraction: null, suggestions: [],
  };
  await mockApp(page);
  await page.route(`**/api/v1/conversations/${ID}`, (route) => route.fulfill({ json: detail }));
  await page.route("**/api/v1/reports/summary**", (route) => route.fulfill({ json: summary }));
  await page.goto(`/chat/${ID}`);
}

test("saved trend survives reload beside an older summary and links to the pinned report", async ({ page }) => {
  const card = reportCard("trend");
  await chat(page, card);
  const region = page.getByRole("region", { name: "Chat spending trend", exact: true });
  await expect(region).toContainText("₹123.45");
  await expect(region).toContainText("Saved report snapshot · 3 transactions across all currencies");
  await region.getByRole("link", { name: /Spent ·/ }).focus();
  await expect(region.getByRole("status")).toContainText("₹123.45");
  await region.getByText("View income and expense trend data table").click();
  await expect(region.getByRole("table")).toContainText("₹123.45");
  await expect(region.getByRole("link", { name: "Open full report" })).toHaveAttribute("href", card.reportHref);
  await page.reload();
  await expect(region).toContainText("₹123.45");
  await region.getByRole("link", { name: "Open full report" }).click();
  await expect(page).toHaveURL(new RegExp("/reports\\?period=range&start=2026-11-01&end=2026-11-24&currency=INR"));
});

test("breakdown preserves exact category and merchant drill-down", async ({ page }) => {
  await chat(page, reportCard("breakdown"));
  const region = page.getByRole("region", { name: "Chat spending breakdown", exact: true });
  await expect(region.getByRole("link", { name: /Uncategorized/ })).toHaveAttribute("href", "/transactions?from=2026-11-01&to=2026-11-24&currency=INR&type=expense&uncategorized=true");
  await expect(region.getByRole("link", { name: /Straße/ })).toHaveAttribute("href", "/transactions?from=2026-11-01&to=2026-11-24&currency=INR&type=expense&merchantKey=strasse");
});

test("empty selected currency offers a separate available-currency report", async ({ page }) => {
  const card = reportCard("trend");
  card.preview = null;
  await chat(page, card);
  const region = page.getByRole("region", { name: "Chat spending trend", exact: true });
  await expect(region).toContainText("No INR transactions in this period");
  await expect(region.getByRole("link", { name: "View USD report" })).toHaveAttribute("href", "/reports?period=range&start=2026-11-01&end=2026-11-24&currency=USD");
  await expect(region.getByRole("group")).toHaveCount(0);
});

test("insights stay readable on narrow dark screens with reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.addInitScript(() => localStorage.setItem("mm-theme", "dark"));
  await chat(page, reportCard("insights"));
  const region = page.getByRole("region", { name: "Chat spending insights", exact: true });
  await expect(region).toContainText("INR spending is ₹123.45; no previous spending.");
  expect(await region.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});
