/** Insights display server facts and preserve exact report drill-down filters. */
import { expect, test } from "@playwright/test";
import { mockApp, overview } from "./fixtures/reports";

test("insight evidence is currency-specific and links to matching transactions", async ({ page }) => {
  const data = overview();
  const report = data.currencies[0];
  report.insights = [{
    kind: "largest_merchant", currency: "INR", period: data.period,
    text: "1 Nov 2026 to 24 Nov 2026 (INR): Largest named merchant: Straße, ₹123.45.",
    current: report.expense.current, previous: null, change: null, changePercent: null,
    sharePercent: null, categoryId: null, merchantKey: "strasse",
  }];
  await mockApp(page, () => data);
  await page.goto("/reports");
  const insights = page.getByRole("region", { name: "Period insights" });
  await expect(insights).toContainText(report.insights[0].text);
  await expect(insights.getByRole("link")).toHaveAttribute("href", "/transactions?from=2026-11-01&to=2026-11-24&currency=INR&type=expense&merchantKey=strasse");
  await page.getByRole("button", { name: "USD", exact: true }).click();
  await expect(insights).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Spent", exact: true })).toContainText("$123.45");
});
