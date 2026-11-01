"use client";

import type { HistoryEntry } from "@moneymoney/contracts";
import { ArrowLeft, Trash2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { balanceSentence, balanceTone } from "@/components/friends/balance-text";
import { SettlementForm } from "@/components/friends/settlement-form";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { formatDay } from "@/lib/format";
import { invalidateFriends, useFriendDetail, useQueryClient } from "@/lib/queries";

function asApiError(caught: unknown): ApiError {
  return caught instanceof ApiError ? caught : new ApiError(0, undefined);
}

/** How a history line reads: the expense's description, or who paid whom for a settlement. */
function entryTitle(entry: HistoryEntry, friendName: string): string {
  if (entry.kind === "shared_expense") return entry.label || "Shared expense";
  const who = entry.effectMinor > 0 ? `You paid ${friendName}` : `${friendName} paid you`;
  return entry.label ? `${who} · ${entry.label}` : who;
}

/**
 * One friend's page: what is owed in each currency, a form to record a settlement, and every
 * shared expense and settlement between you, newest first.
 *
 * Pages stay alive between visits (React `<Activity>`), so the effect re-fetches each time
 * the page is shown, which is when a balance may have moved elsewhere.
 */
export function FriendDetailScreen({ friendId }: { friendId: string }) {
  const queryClient = useQueryClient();
  const detail = useFriendDetail(friendId);

  useEffect(() => {
    void invalidateFriends(queryClient);
  }, [queryClient]);

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex max-w-xl flex-col gap-6 px-4 py-6 md:px-8">
        <Link href="/friends" className="inline-flex items-center gap-1.5 text-sm text-ink-soft hover:text-ink">
          <ArrowLeft className="size-4" aria-hidden /> Friends
        </Link>

        {detail.isPending ? (
          <p className="text-sm text-ink-faint">Loading…</p>
        ) : detail.isError ? (
          <p role="alert" className="text-sm text-danger">
            {asApiError(detail.error).message}
          </p>
        ) : (
          <>
            <header>
              <h1 className="display text-[1.9rem] leading-tight font-semibold">{detail.data.friend.name}</h1>
              {detail.data.friend.balances.length === 0 ? (
                <p className="mt-1 text-ink-soft">You&apos;re settled up.</p>
              ) : (
                <ul className="mt-1 space-y-0.5">
                  {detail.data.friend.balances.map((balance) => (
                    <li key={balance.currency} className={`figure font-medium ${balanceTone(balance)}`}>
                      {balanceSentence(detail.data.friend.name, balance)}
                    </li>
                  ))}
                </ul>
              )}
            </header>

            <SettlementForm friend={detail.data.friend} />

            <section aria-labelledby="history-heading">
              <h2 id="history-heading" className="display text-lg font-semibold">
                History
              </h2>
              {detail.data.history.length === 0 ? (
                <p className="mt-2 text-sm text-ink-faint">Nothing shared yet.</p>
              ) : (
                <ul className="mt-3 divide-y divide-line rounded-[var(--radius-card)] border border-line bg-surface px-5 shadow-[var(--shadow-card)]">
                  {detail.data.history.map((entry) => (
                    <HistoryRow key={`${entry.kind}-${entry.id}`} entry={entry} friendName={detail.data.friend.name} />
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </div>
    </div>
  );
}

/** One line of history; a settlement can be deleted, a shared expense is edited elsewhere. */
function HistoryRow({ entry, friendName }: { entry: HistoryEntry; friendName: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [busy, setBusy] = useState(false);

  async function deleteSettlement() {
    setBusy(true);
    try {
      await unwrap<unknown>(
        api.DELETE("/api/v1/settlements/{settlement_id}", { params: { path: { settlement_id: entry.id } } }),
      );
      await invalidateFriends(queryClient);
      toast("Settlement deleted");
    } catch (caught) {
      toast(asApiError(caught).message, { tone: "error" });
    } finally {
      setBusy(false);
    }
  }

  const friendOwesMore = entry.effectMinor > 0;
  return (
    <li className="flex items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{entryTitle(entry, friendName)}</p>
        <p className="text-xs text-ink-faint">
          {formatDay(entry.occurredOn)} · {entry.kind === "settlement" ? "Settlement" : "Shared expense"}
        </p>
      </div>
      <span className={`figure text-sm font-semibold ${friendOwesMore ? "text-income" : "text-danger"}`}>
        {friendOwesMore ? "+" : "−"}
        {entry.effectFormatted}
      </span>
      {entry.kind === "settlement" ? (
        <button
          type="button"
          onClick={deleteSettlement}
          disabled={busy}
          className="rounded-lg p-1.5 text-ink-faint hover:bg-lavender-wash hover:text-danger disabled:opacity-50"
          aria-label="Delete settlement"
          title="Delete settlement"
        >
          <Trash2 className="size-4" aria-hidden />
        </button>
      ) : null}
    </li>
  );
}
