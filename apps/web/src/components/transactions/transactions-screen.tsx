"use client";

import type { TransactionType, TransactionView } from "@moneymoney/contracts";
import { useQuery } from "@tanstack/react-query";
import { FileUp, History, Plus, Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";

import { ImportStatementDialog } from "@/components/imports/import-dialog";
import { ImportsDialog } from "@/components/imports/imports-dialog";
import { SharedExpenseDialog } from "@/components/transactions/shared-expense-dialog";
import { TransactionDialog } from "@/components/transactions/transaction-dialog";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { NamedIcon } from "@/components/ui/icons";
import { api, unwrap } from "@/lib/api";
import { accountOptionLabel, CURRENCIES, formatDay, paymentLabel, transferRoute } from "@/lib/format";
import { type TransactionFilters, useAccounts, useCategories, useTransactions } from "@/lib/queries";

/** Where the money went from or came into: the account, then the payment method. */
function paidWith(tx: TransactionView): string | null {
  if (tx.type === "transfer") return null; // the route is already the row's title
  return [tx.account?.name, paymentLabel(tx.paymentMethod)].filter(Boolean).join(" · ") || null;
}

/** Income is green, expenses plain, and a transfer neutral: it only moves money around. */
function amountTone(type: TransactionView["type"]): string {
  if (type === "income") return "text-income";
  return type === "transfer" ? "text-ink-soft" : "text-ink";
}

export function TransactionsScreen() {
  const params = useSearchParams();
  const entryId = params.get("entry");
  const entry = useQuery({
    queryKey: ["transactions", "entry", entryId], enabled: !!entryId,
    queryFn: ({ signal }) => unwrap<TransactionView>(api.GET("/api/v1/transactions/{transaction_id}", {
      params: { path: { transaction_id: entryId! } }, signal,
    })),
  });
  const query = params.get("q") ?? "";
  const type = (params.get("type") ?? "") as "" | TransactionType;
  const categoryId = params.get("categoryId") ?? "";
  const accountId = params.get("accountId") ?? "";
  const from = params.get("from") ?? "";
  const to = params.get("to") ?? "";
  const currency = params.get("currency") ?? "";
  const merchantKey = params.get("merchantKey") ?? undefined;
  const otherMerchants = params.get("otherMerchants") === "true";
  const uncategorized = params.get("uncategorized") === "true";
  const searchInput = useRef<HTMLInputElement>(null);

  // Let the native input keep every keystroke while Next transitions its URL snapshot.
  // Reload/back/clear still restore the URL's value; an older render cannot overwrite typing.
  useEffect(() => {
    const latestQuery = new URLSearchParams(window.location.search).get("q") ?? "";
    if (searchInput.current && query === latestQuery) searchInput.current.value = query;
  }, [query]);

  // Next integrates native history with useSearchParams: filters survive reload/back without
  // remounting the page or interrupting text input while a server navigation is pending.
  function changeFilters(updates: Record<string, string | null>, replace = false) {
    const next = new URLSearchParams(window.location.search);
    for (const [key, value] of Object.entries(updates)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    const href = `/transactions${next.size ? `?${next}` : ""}`;
    if (replace) window.history.replaceState(null, "", href);
    else window.history.pushState(null, "", href);
  }
  const [dialog, setDialog] = useState<{ open: boolean; transaction: TransactionView | null }>({
    open: false,
    transaction: null,
  });
  // The shared expense open on top of the transactions page, if any.
  const [sharedId, setSharedId] = useState<string | null>(null);
  // The import dialog is mounted fresh each time it opens, so a new statement never inherits
  // the last one's state (the page stays alive between visits). `reviewId` reopens a preview.
  const [importDialog, setImportDialog] = useState<{ reviewId: string | null } | null>(null);
  const [importsOpen, setImportsOpen] = useState(false);
  const deferredQuery = useDeferredValue(query.trim());
  const categories = useCategories();
  // Archived accounts too: their past transactions are still worth finding.
  const accounts = useAccounts(true);

  const filters: TransactionFilters = useMemo(
    () => ({
      q: deferredQuery || undefined,
      type: type || undefined,
      categoryId: categoryId || undefined,
      accountId: accountId || undefined,
      from: from || undefined,
      to: to || undefined,
      currency: currency || undefined,
      merchantKey,
      otherMerchants: otherMerchants || undefined,
      uncategorized: uncategorized || undefined,
    }),
    [deferredQuery, type, categoryId, accountId, from, to, currency, merchantKey, otherMerchants, uncategorized],
  );
  const transactions = useTransactions(filters);
  const rows = transactions.data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = Boolean(
    filters.q || filters.type || filters.categoryId || filters.accountId || filters.from || filters.to || filters.currency || filters.merchantKey || filters.otherMerchants || filters.uncategorized,
  );
  const categoryOptions = (categories.data ?? []).filter((c) => !type || c.kind === type);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="display text-[1.9rem] leading-tight font-semibold">Transactions</h1>
            <p className="mt-1 text-ink-soft">Everything you&apos;ve recorded, newest first.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button icon={<History className="size-4" aria-hidden />} onClick={() => setImportsOpen(true)}>
              Imports
            </Button>
            <Button icon={<FileUp className="size-4" aria-hidden />} onClick={() => setImportDialog({ reviewId: null })}>
              Import statement
            </Button>
            <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={() => setDialog({ open: true, transaction: null })}>
              Add transaction
            </Button>
          </div>
        </header>

        <div className="mt-6 grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-[minmax(0,2fr)_repeat(6,minmax(0,1fr))]">
          <div className="relative col-span-2 md:col-span-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-faint" aria-hidden />
            <label htmlFor="tx-search" className="sr-only">
              Search transactions
            </label>
            <Input
              id="tx-search"
              type="search"
              ref={searchInput}
              defaultValue={query}
              onChange={(event) => changeFilters({ q: event.target.value }, true)}
              placeholder="Search description, merchant, notes"
              className="pl-9"
              maxLength={100}
            />
          </div>
          <label className="sr-only" htmlFor="tx-type">
            Type
          </label>
          <Select
            id="tx-type"
            value={type}
            onChange={(event) => {
              changeFilters({ type: event.target.value, categoryId: null, uncategorized: null,
                ...(event.target.value !== "expense" ? { otherMerchants: null } : {}) });
            }}
          >
            <option value="">All types</option>
            <option value="expense">Expenses</option>
            <option value="income">Income</option>
            <option value="transfer">Transfers</option>
          </Select>
          <label className="sr-only" htmlFor="tx-category">
            Category
          </label>
          <Select
            id="tx-category"
            value={uncategorized ? "uncategorized" : categoryId}
            disabled={type === "transfer"}
            onChange={(event) => changeFilters({
              categoryId: event.target.value === "uncategorized" ? null : event.target.value,
              uncategorized: event.target.value === "uncategorized" ? "true" : null,
            })}
          >
            <option value="">All categories</option>
            <option value="uncategorized">Uncategorized</option>
            {categoryId && !categoryOptions.some((category) => category.id === categoryId) ? <option value={categoryId}>Selected category</option> : null}
            {categoryOptions.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
          <label className="sr-only" htmlFor="tx-account">
            Account
          </label>
          <Select id="tx-account" value={accountId} onChange={(event) => changeFilters({ accountId: event.target.value })}>
            <option value="">All accounts</option>
            {(accounts.data ?? []).map((account) => (
              <option key={account.id} value={account.id}>
                {accountOptionLabel(account)}
              </option>
            ))}
          </Select>
          <label className="sr-only" htmlFor="tx-from">
            From date
          </label>
          <Input id="tx-from" type="date" value={from} max={to || undefined} onChange={(event) => changeFilters({ from: event.target.value }, true)} />
          <label className="sr-only" htmlFor="tx-to">
            To date
          </label>
          <Input id="tx-to" type="date" value={to} min={from || undefined} onChange={(event) => changeFilters({ to: event.target.value }, true)} />
          <label htmlFor="tx-currency" className="sr-only">Currency</label>
          <Select id="tx-currency" value={currency} onChange={(event) => changeFilters({ currency: event.target.value, otherMerchants: null })}>
            <option value="">All currencies</option>
            {CURRENCIES.map(([code, name]) => <option key={code} value={code}>{code} · {name}</option>)}
            {currency && !CURRENCIES.some(([code]) => code === currency) ? <option value={currency}>{currency}</option> : null}
          </Select>
        </div>

        {filtered ? <div className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          {merchantKey || otherMerchants ? <span className="min-w-0 rounded-lg bg-sky-wash px-3 py-2 text-sky-ink [overflow-wrap:anywhere]">
            {otherMerchants ? "Other merchants · ranked for these dates and currency" : `Exact merchant: ${merchantKey}`}
            <button type="button" className="ml-3 font-medium underline" aria-label="Remove merchant filter"
              onClick={() => changeFilters({ merchantKey: null, otherMerchants: null })}>Remove</button>
          </span> : null}
          <Button size="sm" variant="ghost" onClick={() => window.history.pushState(null, "", "/transactions")}>Clear filters</Button>
        </div> : null}

        <section className="mt-5 overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]">
          {transactions.isPending ? (
            <p className="px-5 py-10 text-center text-sm text-ink-faint">Loading transactions…</p>
          ) : transactions.isError ? (
            <div className="flex flex-col items-center gap-3 px-5 py-10 text-center">
              <p className="text-sm text-ink-soft">{transactions.error.message}</p>
              <Button size="sm" onClick={() => transactions.refetch()}>
                Try again
              </Button>
            </div>
          ) : rows.length === 0 ? (
            <div className="px-5 py-12 text-center">
              <p className="display text-lg font-semibold">{filtered ? "No matches" : "Nothing recorded yet"}</p>
              <p className="mx-auto mt-1 max-w-sm text-sm text-ink-soft">
                {filtered
                  ? "Try a wider date range or clear a filter."
                  : "Add one here, or tell the assistant something like “Spent ₹120 on chai”."}
              </p>
            </div>
          ) : (
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Transactions</caption>
              <thead className="hidden border-b border-line bg-paper/70 text-xs tracking-wide text-ink-faint uppercase md:table-header-group">
                <tr>
                  <th scope="col" className="px-5 py-2.5 font-semibold">Date</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Description</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Category</th>
                  <th scope="col" className="px-3 py-2.5 font-semibold">Paid with</th>
                  <th scope="col" className="px-5 py-2.5 text-right font-semibold">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {rows.map((tx) => {
                  const isTransfer = tx.type === "transfer";
                  const categoryName = isTransfer ? "Transfer" : (tx.category?.name ?? "Uncategorised");
                  return (
                  <tr
                    key={tx.id}
                    className="cursor-pointer transition-colors hover:bg-sky-wash/40"
                    onClick={() => setDialog({ open: true, transaction: tx })}
                  >
                    <td className="hidden px-5 py-3 whitespace-nowrap text-ink-soft md:table-cell">{formatDay(tx.occurredOn)}</td>
                    <td className="px-5 py-3 md:px-3">
                      <button
                        type="button"
                        className="text-left font-medium text-ink hover:underline"
                        onClick={(event) => {
                          event.stopPropagation();
                          setDialog({ open: true, transaction: tx });
                        }}
                      >
                        {isTransfer ? transferRoute(tx) : (tx.description ?? tx.category?.name ?? "Transaction")}
                      </button>
                      {tx.sharedExpenseId ? (
                        <span className="ml-2 rounded-full bg-sky-wash px-2 py-0.5 text-xs font-medium text-sky-ink">
                          Shared
                        </span>
                      ) : null}
                      {tx.source === "import" ? (
                        <span className="ml-2 rounded-full bg-paper px-2 py-0.5 text-xs font-medium text-ink-soft">
                          Imported
                        </span>
                      ) : null}
                      <span className="block text-xs text-ink-faint">
                        {[isTransfer ? tx.description : null, tx.merchant, tx.source === "chat" ? "from chat" : null].filter(Boolean).join(" · ") || " "}
                      </span>
                      <span className="block text-xs text-ink-faint md:hidden">
                        {[formatDay(tx.occurredOn), categoryName, isTransfer ? null : tx.account?.name]
                          .filter(Boolean)
                          .join(" · ")}
                      </span>
                    </td>
                    <td className="hidden px-3 py-3 md:table-cell">
                      <span className="inline-flex items-center gap-1.5 text-ink-soft">
                        <NamedIcon
                          name={isTransfer ? "arrow-left-right" : tx.category?.icon}
                          className="size-3.5 text-sky-deep"
                        />
                        {categoryName}
                      </span>
                    </td>
                    <td className="hidden px-3 py-3 text-ink-soft md:table-cell">{paidWith(tx) ?? "—"}</td>
                    <td className={`figure px-5 py-3 text-right text-base font-semibold whitespace-nowrap ${amountTone(tx.type)}`}>
                      {tx.type === "income" ? "+" : ""}
                      {tx.amountFormatted}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </section>
        {transactions.hasNextPage ? (
          <div className="mt-4 flex justify-center">
            <Button onClick={() => transactions.fetchNextPage()} busy={transactions.isFetchingNextPage}>
              Show more
            </Button>
          </div>
        ) : null}
      </div>
      {entryId && entry.isError && <p role="alert" className="mx-auto p-4 text-danger">{entry.error.message} <Button onClick={() => changeFilters({ entry: null }, true)}>Dismiss</Button></p>}
      <TransactionDialog
        open={dialog.open || Boolean(entryId && entry.data)}
        transaction={entryId && entry.data ? entry.data : dialog.transaction}
        onClose={() => {
          if (entryId) changeFilters({ entry: null }, true);
          setDialog({ open: false, transaction: null });
        }}
        onOpenShared={(id) => {
          if (entryId) changeFilters({ entry: null }, true);
          setDialog({ open: false, transaction: null });
          setSharedId(id);
        }}
      />
      <SharedExpenseDialog sharedExpenseId={sharedId} onClose={() => setSharedId(null)} />
      {importDialog ? (
        <ImportStatementDialog initialImportId={importDialog.reviewId} onClose={() => setImportDialog(null)} />
      ) : null}
      <ImportsDialog
        open={importsOpen}
        onClose={() => setImportsOpen(false)}
        onReview={(importId) => {
          setImportsOpen(false);
          setImportDialog({ reviewId: importId });
        }}
      />
    </div>
  );
}
