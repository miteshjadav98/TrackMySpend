"use client";

import type { TransactionType, TransactionView } from "@moneymoney/contracts";
import { Plus, Search } from "lucide-react";
import { useDeferredValue, useMemo, useState } from "react";

import { TransactionDialog } from "@/components/transactions/transaction-dialog";
import { Button } from "@/components/ui/button";
import { Input, Select } from "@/components/ui/field";
import { NamedIcon } from "@/components/ui/icons";
import { formatDay, paymentLabel } from "@/lib/format";
import { type TransactionFilters, useCategories, useTransactions } from "@/lib/queries";

export function TransactionsScreen() {
  const [query, setQuery] = useState("");
  const [type, setType] = useState<"" | TransactionType>("");
  const [categoryId, setCategoryId] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [dialog, setDialog] = useState<{ open: boolean; transaction: TransactionView | null }>({
    open: false,
    transaction: null,
  });
  const deferredQuery = useDeferredValue(query.trim());
  const categories = useCategories();

  const filters: TransactionFilters = useMemo(
    () => ({
      q: deferredQuery || undefined,
      type: type || undefined,
      categoryId: categoryId || undefined,
      from: from || undefined,
      to: to || undefined,
    }),
    [deferredQuery, type, categoryId, from, to],
  );
  const transactions = useTransactions(filters);
  const rows = transactions.data?.pages.flatMap((page) => page.items) ?? [];
  const filtered = Boolean(filters.q || filters.type || filters.categoryId || filters.from || filters.to);
  const categoryOptions = (categories.data ?? []).filter((c) => !type || c.kind === type);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-4 py-6 md:px-8">
        <header className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="display text-[1.9rem] leading-tight font-semibold">Transactions</h1>
            <p className="mt-1 text-ink-soft">Everything you&apos;ve recorded, newest first.</p>
          </div>
          <Button variant="primary" icon={<Plus className="size-4" aria-hidden />} onClick={() => setDialog({ open: true, transaction: null })}>
            Add transaction
          </Button>
        </header>

        <div className="mt-6 grid grid-cols-2 gap-2 md:grid-cols-[minmax(0,2fr)_repeat(4,minmax(0,1fr))]">
          <div className="relative col-span-2 md:col-span-1">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-ink-faint" aria-hidden />
            <label htmlFor="tx-search" className="sr-only">
              Search transactions
            </label>
            <Input
              id="tx-search"
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
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
              setType(event.target.value as "" | TransactionType);
              setCategoryId("");
            }}
          >
            <option value="">All types</option>
            <option value="expense">Expenses</option>
            <option value="income">Income</option>
          </Select>
          <label className="sr-only" htmlFor="tx-category">
            Category
          </label>
          <Select id="tx-category" value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
            <option value="">All categories</option>
            {categoryOptions.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </Select>
          <label className="sr-only" htmlFor="tx-from">
            From date
          </label>
          <Input id="tx-from" type="date" value={from} max={to || undefined} onChange={(event) => setFrom(event.target.value)} />
          <label className="sr-only" htmlFor="tx-to">
            To date
          </label>
          <Input id="tx-to" type="date" value={to} min={from || undefined} onChange={(event) => setTo(event.target.value)} />
        </div>

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
                {rows.map((tx) => (
                  <tr
                    key={tx.id}
                    className="cursor-pointer transition-colors hover:bg-lavender-wash/40"
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
                        {tx.description ?? tx.category?.name ?? "Transaction"}
                      </button>
                      <span className="block text-xs text-ink-faint">
                        {[tx.merchant, tx.source === "chat" ? "from chat" : null].filter(Boolean).join(" · ") || " "}
                      </span>
                      <span className="block text-xs text-ink-faint md:hidden">
                        {formatDay(tx.occurredOn)} · {tx.category?.name ?? "Uncategorised"}
                      </span>
                    </td>
                    <td className="hidden px-3 py-3 md:table-cell">
                      <span className="inline-flex items-center gap-1.5 text-ink-soft">
                        <NamedIcon name={tx.category?.icon} className="size-3.5 text-lavender-deep" />
                        {tx.category?.name ?? "Uncategorised"}
                      </span>
                    </td>
                    <td className="hidden px-3 py-3 text-ink-soft md:table-cell">{paymentLabel(tx.paymentMethod) ?? "—"}</td>
                    <td className={`figure px-5 py-3 text-right text-base font-semibold whitespace-nowrap ${tx.type === "income" ? "text-income" : "text-ink"}`}>
                      {tx.type === "income" ? "+" : ""}
                      {tx.amountFormatted}
                    </td>
                  </tr>
                ))}
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
      <TransactionDialog
        open={dialog.open}
        transaction={dialog.transaction}
        onClose={() => setDialog({ open: false, transaction: null })}
      />
    </div>
  );
}
