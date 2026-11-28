import type { AccountOverview, AccountView } from "@moneymoney/contracts";
import { expect, test, type Page } from "@playwright/test";
import { mockApp, money } from "./fixtures/reports";

const bank: AccountView = {
  id: "01940000-0000-7000-8000-000000000010", name: "Salary account", kind: "bank", currency: "INR",
  isArchived: false, createdAt: "2026-10-01T00:00:00Z", updatedAt: "2026-11-01T00:00:00Z",
  balance: money("INR", -2010, "-₹20.10"), balanceState: "overdraft", balanceAnchor: { asOf: "2026-11-01", amountMinor: -2010 },
};
const card: AccountView = { ...bank, id: "01940000-0000-7000-8000-000000000011", kind: "credit_card", name: "Travel card",
  currency: "USD", balance: null, balanceState: "missing_anchor", balanceAnchor: null };
const old = { ...bank, name: "Old bank", isArchived: true, id: "01940000-0000-7000-8000-000000000012" };

async function setup(page: Page) {
  const accounts = [{ ...bank }, { ...card }];
  const overview = (): AccountOverview => ({
    accounts, positions: accounts.map(account => {
      const zero = money(account.currency, 0, account.currency === "USD" ? "$0.00" : "₹0.00");
      return { currency: account.currency, assets: account.balance ?? zero, liabilities: zero, net: account.balance ?? zero,
        excludedAccounts: account.balance === null ? [account] : [] };
    }),
  });
  await mockApp(page);
  await page.route("**/api/v1/accounts?**", route => route.fulfill({ json: [...accounts, old] }));
  await page.route("**/api/v1/accounts/overview", route => route.fulfill({ json: overview() }));
  await page.route("**/api/v1/accounts/*/ledger?**", route => {
    const first = new URL(route.request().url()).searchParams.get("offset") === "0";
    return route.fulfill({ json: { nextOffset: first ? 25 : null, items: [{
      occurredOn: first ? "2026-11-02" : "2026-11-01", sourceKind: first ? "transaction" : "settlement",
      sourceId: first ? "01940000-0000-7000-8000-000000000031" : "01940000-0000-7000-8000-000000000032",
      cashEffect: bank.balance, balanceAfter: bank.balance,
    }] } });
  });
  return accounts;
}

test("groups known balances by currency and opens paginated account history", async ({ page }) => {
  await setup(page);
  await page.goto("/accounts");
  await expect(page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Accounts" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("region", { name: "INR" })).toContainText("-₹20.10 Overdraft");
  await expect(page.getByRole("region", { name: "INR" })).toContainText("Known net position");
  await expect(page.getByRole("region", { name: "USD" })).toContainText("Excluded from totals (1): Travel card");
  await page.getByRole("button", { name: "Show archived accounts" }).click();
  await expect(page.getByRole("link", { name: /Old bank/ })).toContainText("Archived");
  await page.getByRole("link", { name: /Salary account/ }).click();
  await expect(page).toHaveURL(new RegExp(`\\?account=${bank.id}$`));
  await page.reload();
  await expect(page.getByRole("link", { name: "View transaction" })).toHaveAttribute("href", /transactions\?entry=.*31$/);
  await page.getByRole("button", { name: "Load older movements" }).click();
  await expect(page.getByText("Settlement", { exact: true })).toBeVisible();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "Accounts", exact: true })).toBeVisible();
});

test("reviews a credit anchor with exact minor units before saving", async ({ page }) => {
  const accounts = await setup(page);
  const writes: unknown[] = [];
  await page.route(`**/api/v1/accounts/${card.id}`, async route => {
    const body = route.request().postDataJSON();
    writes.push(body);
    accounts[1] = { ...card, balanceAnchor: body.balanceAnchor, balanceState: "credit", balance: money("USD", -101, "-$1.01") };
    await route.fulfill({ json: accounts[1] });
  });
  await page.goto(`/accounts?account=${card.id}`);
  await page.getByRole("button", { name: "Set opening balance" }).click();
  const dialog = page.getByRole("dialog");
  await page.getByLabel("Balance type").selectOption("negative");
  const openingDate = page.getByLabel("At start of day");
  await openingDate.fill("2099-01-01");
  await page.getByLabel("Amount (USD)").fill("1.01");
  await page.getByRole("button", { name: "Review opening balance" }).click();
  expect(await openingDate.evaluate((input: HTMLInputElement) => input.validity.rangeOverflow)).toBe(true);
  await expect(dialog).toHaveAccessibleName("Opening balance");
  await openingDate.fill("2026-10-01");
  await page.getByLabel("Amount (USD)").fill("1.001");
  await page.getByRole("button", { name: "Review opening balance" }).click();
  await expect(dialog.getByRole("alert")).toContainText("2 decimal places");
  await page.getByLabel("Amount (USD)").fill("1.01");
  await page.getByRole("button", { name: "Review opening balance" }).click();
  await expect(dialog).toContainText("Credit balance at the start of 2026-10-01");
  expect(writes).toEqual([]);
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(dialog).toHaveCount(0);
  expect(writes).toEqual([{ expectedUpdatedAt: card.updatedAt, balanceAnchor: { amountMinor: -101, asOf: "2026-10-01" } }]);
  await expect(page.getByRole("main")).toContainText("-$1.01 Credit balance");
  await expect(page.getByText(/^Opening balance .*1\.01$/)).toBeVisible();
});

test("protects an inaccessible deep link and supports narrow dark navigation", async ({ page }) => {
  await setup(page);
  await page.setViewportSize({ width: 375, height: 760 });
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/accounts?account=someone-elses-account");
  await expect(page.getByRole("main").getByRole("alert")).toHaveText("Account unavailable.");
  await expect(page.getByRole("button", { name: /opening balance/i })).toHaveCount(0);
  await page.getByRole("button", { name: "Open navigation" }).click();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Accounts" }).click();
  await expect(page.getByRole("region", { name: "INR" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});

test("keeps a stale correction visible and recoverable", async ({ page }) => {
  await setup(page);
  await page.route(`**/api/v1/accounts/${bank.id}`, route => route.fulfill({ status: 409, json: { error: { code: "account_changed", message: "Account changed" } } }));
  await page.goto(`/accounts?account=${bank.id}`);
  await page.getByRole("button", { name: "Correct opening balance" }).click();
  await page.getByRole("button", { name: "Review opening balance" }).click();
  await page.getByRole("button", { name: "Confirm and save" }).click();
  await expect(page.getByRole("dialog").getByRole("alert")).toContainText("This account changed");
});

test("recovers from an overview failure and offers account setup when empty", async ({ page }) => {
  await mockApp(page);
  let fail = true;
  await page.route("**/api/v1/accounts/overview", route => route.fulfill(fail
    ? { status: 400, json: { error: { code: "unavailable", message: "Accounts unavailable" } } }
    : { json: { accounts: [], positions: [] } }));
  await page.goto("/accounts");
  await expect(page.getByRole("main").getByRole("alert")).toContainText("Accounts unavailable");
  fail = false;
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("link", { name: "Add an account" })).toHaveAttribute("href", "/settings#accounts");
});

test("opens the transaction identified by a movement", async ({ page }) => {
  await setup(page);
  await page.route("**/api/v1/transactions/*31", route => route.fulfill({ json: {
    id: "01940000-0000-7000-8000-000000000031", type: "expense", amount: "20.10", amountMinor: 2010,
    currency: "INR", amountFormatted: "₹20.10", occurredOn: "2026-11-02", account: bank, toAccount: null,
    category: null, description: "Bus fare", merchant: null, paymentMethod: null, notes: null, version: 1,
    source: "manual", sharedExpenseId: null,
  } }));
  await page.goto(`/accounts?account=${bank.id}`);
  await page.getByRole("link", { name: "View transaction" }).click();
  await expect(page.getByRole("dialog", { name: "Edit transaction" })).toBeVisible();
  await expect(page.getByLabel("Amount", { exact: true })).toHaveValue("20.10");
});
