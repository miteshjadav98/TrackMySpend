"use client";

import type {
  CurrencySummary,
  SummaryInteraction,
  TransactionListInteraction,
  TransactionsSavedInteraction,
  TransactionView,
} from "@moneymoney/contracts";
import { ArrowRight, Pencil, RotateCcw, Undo2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { TransactionDialog } from "@/components/transactions/transaction-dialog";
import { NamedIcon } from "@/components/ui/icons";
import { useToast } from "@/components/ui/toast";
import { api, unwrap } from "@/lib/api";
import { formatDay, paymentLabel } from "@/lib/format";
import { invalidateLedger, useQueryClient } from "@/lib/queries";

function Amount({ tx, className = "" }: { tx: TransactionView; className?: string }) {
  return (
    <span className={`figure font-semibold ${tx.type === "income" ? "text-income" : "text-ink"} ${className}`}>
      {tx.type === "income" ? "+" : ""}
      {tx.amountFormatted}
    </span>
  );
}

/** A saved entry, shown as a ledger slip with Undo and Edit right where it landed. */
export function SavedCard({ interaction }: { interaction: TransactionsSavedInteraction }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<TransactionView | null>(null);

  async function undo(tx: TransactionView) {
    try {
      await unwrap(
        api.DELETE("/api/v1/transactions/{transaction_id}", {
          params: { path: { transaction_id: tx.id } },
        }),
      );
      setRemoved((current) => new Set(current).add(tx.id));
      await invalidateLedger(queryClient);
    } catch (error) {
      toast((error as Error).message, { tone: "error" });
    }
  }

  async function restore(tx: TransactionView) {
    try {
      await unwrap(
        api.POST("/api/v1/transactions/{transaction_id}/restore", {
          params: { path: { transaction_id: tx.id } },
        }),
      );
      setRemoved((current) => {
        const next = new Set(current);
        next.delete(tx.id);
        return next;
      });
      await invalidateLedger(queryClient);
    } catch (error) {
      toast((error as Error).message, { tone: "error" });
    }
  }

  return (
    <div className="mt-2 overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <ul className="divide-y divide-dashed divide-line">
        {interaction.transactions.map((tx) => {
          const gone = removed.has(tx.id);
          const meta = [tx.category?.name ?? "Uncategorised", formatDay(tx.occurredOn), paymentLabel(tx.paymentMethod)]
            .filter(Boolean)
            .join(" · ");
          return (
            <li key={tx.id} className={`flex items-center gap-3 px-4 py-3 ${gone ? "opacity-55" : ""}`}>
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-lavender-wash text-lavender-ink">
                <NamedIcon name={tx.category?.icon} />
              </span>
              <div className="min-w-0 flex-1">
                <p className={`truncate font-medium ${gone ? "line-through" : ""}`}>
                  {tx.description ?? tx.category?.name ?? "Transaction"}
                </p>
                <p className="truncate text-xs text-ink-faint">{gone ? "Removed from your books" : meta}</p>
              </div>
              <Amount tx={tx} className={`text-lg ${gone ? "line-through" : ""}`} />
              <div className="flex shrink-0 gap-0.5">
                {gone ? (
                  <button
                    type="button"
                    onClick={() => restore(tx)}
                    className="rounded-lg p-1.5 text-ink-faint hover:bg-lavender-wash hover:text-ink"
                    aria-label={`Restore ${tx.amountFormatted}`}
                    title="Restore"
                  >
                    <RotateCcw className="size-4" aria-hidden />
                  </button>
                ) : (
                  <>
                    <button
                      type="button"
                      onClick={() => setEditing(tx)}
                      className="rounded-lg p-1.5 text-ink-faint hover:bg-lavender-wash hover:text-ink"
                      aria-label={`Edit ${tx.amountFormatted}`}
                      title="Edit"
                    >
                      <Pencil className="size-4" aria-hidden />
                    </button>
                    <button
                      type="button"
                      onClick={() => undo(tx)}
                      className="rounded-lg p-1.5 text-ink-faint hover:bg-lavender-wash hover:text-ink"
                      aria-label={`Undo ${tx.amountFormatted}`}
                      title="Undo"
                    >
                      <Undo2 className="size-4" aria-hidden />
                    </button>
                  </>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      {interaction.totals.length ? (
        <div className="flex justify-end gap-4 border-t border-line bg-paper/60 px-4 py-2 text-sm text-ink-soft">
          {interaction.totals.map((total) => (
            <span key={total.currency}>
              Total <span className="figure font-semibold text-ink">{total.formatted}</span>
            </span>
          ))}
        </div>
      ) : null}
      <TransactionDialog open={editing !== null} transaction={editing} onClose={() => setEditing(null)} />
    </div>
  );
}

function CurrencyBlock({ summary }: { summary: CurrencySummary }) {
  const net = summary.net.amountMinor;
  const top = summary.expenseByCategory.slice(0, 6);
  return (
    <div className="flex flex-col gap-4">
      <dl className="grid grid-cols-3 gap-3">
        <div>
          <dt className="text-xs text-ink-faint">Spent</dt>
          <dd className="figure text-xl font-semibold">{summary.expense.formatted}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-faint">Received</dt>
          <dd className="figure text-xl font-semibold text-income">{summary.income.formatted}</dd>
        </div>
        <div>
          <dt className="text-xs text-ink-faint">Net</dt>
          <dd className={`figure text-xl font-semibold ${net >= 0 ? "text-income" : "text-ink"}`}>
            {summary.net.formatted}
          </dd>
        </div>
      </dl>
      {top.length ? (
        <ul className="flex flex-col gap-2.5" aria-label="Spending by category">
          {top.map((category) => (
            <li key={category.slug}>
              <div className="flex items-baseline justify-between gap-3 text-sm">
                <span className="flex items-center gap-1.5 truncate">
                  <NamedIcon name={category.icon} className="size-3.5 text-lavender-deep" />
                  {category.name}
                </span>
                <span className="shrink-0 text-ink-soft">
                  <span className="figure font-semibold text-ink">{category.total.formatted}</span>
                  <span className="ml-2 text-xs">{category.sharePercent}%</span>
                </span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-lavender-wash" aria-hidden>
                <div
                  className="h-full rounded-full bg-lavender-deep"
                  style={{ width: `${Math.max(2, category.sharePercent)}%` }}
                />
              </div>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

export function SummaryCard({ interaction }: { interaction: SummaryInteraction }) {
  const { summary } = interaction;
  return (
    <div className="mt-2 rounded-[var(--radius-card)] border border-line bg-surface p-4 shadow-[var(--shadow-card)]">
      <div className="mb-4 flex items-baseline justify-between gap-3">
        <h3 className="display text-base font-semibold">{summary.period.label}</h3>
        <span className="text-xs text-ink-faint">
          {summary.transactionCount} {summary.transactionCount === 1 ? "transaction" : "transactions"}
        </span>
      </div>
      {summary.currencies.length ? (
        <div className="flex flex-col gap-6">
          {summary.currencies.map((currency) => (
            <section key={currency.currency} aria-label={currency.currency}>
              {summary.currencies.length > 1 ? (
                <h4 className="mb-2 text-xs font-semibold tracking-wide text-ink-faint uppercase">
                  {currency.currency}
                </h4>
              ) : null}
              <CurrencyBlock summary={currency} />
            </section>
          ))}
        </div>
      ) : (
        <p className="text-sm text-ink-soft">Nothing recorded for this period yet.</p>
      )}
      <p className="mt-4 border-t border-dashed border-line pt-3 text-xs text-ink-faint">
        {summary.dataSource}, {summary.period.start} to {summary.period.end}.
      </p>
    </div>
  );
}

export function TransactionListCard({ interaction }: { interaction: TransactionListInteraction }) {
  return (
    <div className="mt-2 overflow-hidden rounded-[var(--radius-card)] border border-line bg-surface shadow-[var(--shadow-card)]">
      <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3">
        <h3 className="display text-base font-semibold">{interaction.title}</h3>
        {interaction.period ? <span className="text-xs text-ink-faint">{interaction.period.label}</span> : null}
      </div>
      {interaction.transactions.length ? (
        <ul className="divide-y divide-line">
          {interaction.transactions.map((tx) => (
            <li key={tx.id} className="flex items-center gap-3 px-4 py-2.5">
              <span className="w-24 shrink-0 text-xs text-ink-faint">{formatDay(tx.occurredOn)}</span>
              <span className="min-w-0 flex-1 truncate text-sm">
                {tx.description ?? tx.category?.name ?? "Transaction"}
              </span>
              <Amount tx={tx} />
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 py-3 text-sm text-ink-soft">No matching transactions.</p>
      )}
      <Link
        href="/transactions"
        className="flex items-center justify-end gap-1 border-t border-line px-4 py-2 text-sm font-medium text-lavender-deep hover:bg-lavender-wash/50"
      >
        All transactions <ArrowRight className="size-3.5" aria-hidden />
      </Link>
    </div>
  );
}
