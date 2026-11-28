"use client";

import type { AccountOverview, AccountView, BalanceLedger } from "@moneymoney/contracts";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { AnchorEditor } from "@/components/accounts/anchor-editor";
import { SharedExpenseDialog } from "@/components/transactions/shared-expense-dialog";
import { Button } from "@/components/ui/button";
import { api, unwrap } from "@/lib/api";
import { formatMinor } from "@/lib/format";
import { useAccounts, useMe } from "@/lib/queries";

const panel = "rounded-[var(--radius-card)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]";
const link = "font-medium text-sky-deep underline underline-offset-4";
const stateLabel = { held: "Held", owed: "Owed", overdraft: "Overdraft", credit: "Credit balance", missing_anchor: "Balance unknown", currency_mismatch: "Balance unknown" };

function Retry({ error, retry }: { error: Error; retry: () => void }) {
  return <div role="alert" className="space-y-3"><p>{error.message}</p><Button onClick={retry}>Try again</Button></div>;
}

function AccountSummary({ account }: { account: AccountView }) {
  const liability = account.kind === "credit_card" || account.kind === "loan";
  return <div className="flex flex-wrap items-start justify-between gap-x-5 gap-y-1">
    <div className="min-w-0">
      <p className="break-words font-semibold">{account.name}</p>
      <p className="text-sm text-ink-soft capitalize">{account.kind.replace("_", " ")} · {liability ? "Liability" : "Asset"} · {account.currency}{account.isArchived && " · Archived"}</p>
    </div>
    <div>
      <p className="figure font-medium">{account.balance?.formatted} {stateLabel[account.balanceState]}</p>
      {account.balanceAnchor && <p className="text-xs text-ink-soft">Opening date {account.balanceAnchor.asOf}</p>}
      {account.balanceState === "currency_mismatch" && <p className="text-sm text-ink-soft">History includes another currency.</p>}
    </div>
  </div>;
}

function AccountList({ accounts }: { accounts: AccountView[] }) {
  return <ul className="divide-y divide-line">{accounts.map(account => <li key={account.id}>
    <Link className="block rounded-md px-2 py-3 hover:bg-sky-wash" href={`/accounts?account=${account.id}`}><AccountSummary account={account} /></Link>
  </li>)}</ul>;
}

function ArchivedAccounts() {
  const query = useAccounts(true);
  if (query.isPending) return <p role="status">Loading archived accounts…</p>;
  if (query.isError) return <Retry error={query.error} retry={query.refetch} />;
  const archived = query.data.filter(a => a.isArchived);
  return archived.length ? <AccountList accounts={archived} /> : <p>No archived accounts.</p>;
}

function Overview() {
  const [archived, setArchived] = useState(false);
  const query = useQuery({ queryKey: ["accounts", "overview"], queryFn: ({ signal }) => unwrap<AccountOverview>(api.GET("/api/v1/accounts/overview", { signal })) });
  if (query.isPending) return <p role="status">Loading accounts…</p>;
  if (query.isError) return <Retry error={query.error} retry={query.refetch} />;
  return <>
    {query.data.accounts.length === 0 && <p className={panel}>No active accounts. <Link href="/settings#accounts" className={link}>Add an account</Link></p>}
    {query.data.positions.map(position => <section aria-label={position.currency} className={panel} key={position.currency}>
      <h2 className="display text-xl font-semibold">{position.currency}</h2>
      {query.data.accounts.some(a => a.currency === position.currency && a.balance !== null) ? <dl className="mt-3 grid gap-3 rounded-lg bg-paper p-4 sm:grid-cols-3">
        {([["Known assets", position.assets], ["Known liabilities", position.liabilities], ["Known net position", position.net]] as const).map(([label, money]) =>
          <div key={label}><dt className="text-sm text-ink-soft">{label}</dt><dd className="figure text-lg font-semibold">{money.formatted}</dd></div>)}
      </dl> : <p className="mt-3 text-ink-soft">No known balances in {position.currency}.</p>}
      {position.excludedAccounts.length > 0 && <p className="my-3 text-sm text-ink-soft">Excluded from totals ({position.excludedAccounts.length}): {position.excludedAccounts.map(a => a.name).join(", ")}.</p>}
      <AccountList accounts={query.data.accounts.filter(a => a.currency === position.currency)} />
    </section>)}
    <div className="space-y-3"><Button aria-expanded={archived} onClick={() => setArchived(!archived)}>{archived ? "Hide" : "Show"} archived accounts</Button>{archived && <ArchivedAccounts />}</div>
  </>;
}

function History({ account }: { account: AccountView }) {
  const [shared, setShared] = useState<string | null>(null);
  const query = useInfiniteQuery({ queryKey: ["accounts", "ledger", account.id], initialPageParam: 0,
    queryFn: ({ pageParam, signal }) => unwrap<BalanceLedger>(api.GET("/api/v1/accounts/{account_id}/ledger", {
      params: { path: { account_id: account.id }, query: { offset: pageParam, limit: 25 } }, signal,
    })), getNextPageParam: page => page.nextOffset ?? undefined });
  if (query.isPending) return <p role="status">Loading history…</p>;
  if (query.isError && !query.data) return <Retry error={query.error} retry={query.refetch} />;
  const items = query.data?.pages.flatMap(p => p.items) ?? [];
  return <>
    {!items.length && <p>No movements since the opening date.</p>}
    <ul className="divide-y divide-line">{items.map(row => <li key={row.sourceKind + row.sourceId} className="flex flex-wrap items-center justify-between gap-3 py-3">
      <div>{row.sourceKind === "transaction" ? <Link className={link} href={`/transactions?entry=${row.sourceId}`}>View transaction</Link> :
        row.sourceKind === "shared_expense" ? <button className={link} onClick={() => setShared(row.sourceId)}>View shared expense</button> : <span>Settlement</span>}
        <p className="text-sm text-ink-soft">{row.occurredOn}</p></div>
      <div className="figure"><p>{row.cashEffect.formatted}</p><p className="text-sm text-ink-soft">Balance after: {row.balanceAfter?.formatted ?? "Unknown"}</p></div>
    </li>)}</ul>
    {query.isFetchNextPageError && <p role="alert">{query.error?.message}</p>}
    {query.hasNextPage && <Button busy={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>Load older movements</Button>}
    {shared && <SharedExpenseDialog sharedExpenseId={shared} onClose={() => setShared(null)} />}
  </>;
}

function Detail({ id }: { id: string }) {
  const accounts = useAccounts(true);
  const locale = useMe().data?.profile.locale;
  const [editing, setEditing] = useState(false);
  const account = accounts.data?.find(a => a.id === id);
  if (accounts.isPending) return <p role="status">Loading account…</p>;
  if (accounts.isError) return <Retry error={accounts.error} retry={accounts.refetch} />;
  if (!account) return <p role="alert">Account unavailable.</p>;
  const anchor = account.balanceAnchor;
  return <>
    <section className={panel}><AccountSummary account={account} />
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        {anchor && <p className="text-sm text-ink-soft">Opening balance <strong className="figure text-ink">{formatMinor(anchor.amountMinor, account.currency, locale)}</strong></p>}
        <Button onClick={() => setEditing(true)}>{anchor ? "Correct" : "Set"} opening balance</Button>
      </div>
    </section>
    <section className={panel}><h2 className="display mb-3 text-xl font-semibold">Balance history</h2>
      {anchor ? <History account={account} /> : <p>Set an opening balance to see the running balance.</p>}
    </section>
    {editing && <AnchorEditor account={account} close={() => setEditing(false)} />}
  </>;
}

export function AccountsScreen() {
  const id = useSearchParams().get("account");
  return <div className="min-h-0 flex-1 overflow-y-auto"><div className="mx-auto grid max-w-4xl gap-5 px-4 py-6 md:px-8">
    <header className="flex flex-wrap items-baseline justify-between gap-3"><h1 className="display text-[1.9rem] font-semibold">{id ? "Account details" : "Accounts"}</h1>
      <Link className={link} href={id ? "/accounts" : "/settings#accounts"}>{id ? "All accounts" : "Manage accounts"}</Link></header>
    {id ? <Detail key={id} id={id} /> : <Overview />}
  </div></div>;
}
