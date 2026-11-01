"use client";

import type { AccountKind, AccountUpdate, AccountView } from "@moneymoney/contracts";
import { Archive, ArchiveRestore, Pencil, Plus } from "lucide-react";
import { type FormEvent, useState } from "react";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { CURRENCIES } from "@/lib/format";
import { invalidateAccounts, useAccounts, useMe, useQueryClient } from "@/lib/queries";

const KINDS: { value: AccountKind; label: string }[] = [
  { value: "bank", label: "Bank account" },
  { value: "credit_card", label: "Credit card" },
  { value: "wallet", label: "Wallet" },
  { value: "cash", label: "Cash" },
  { value: "other", label: "Other" },
];

function kindLabel(kind: AccountKind): string {
  return KINDS.find((option) => option.value === kind)?.label ?? kind;
}

function asApiError(caught: unknown): ApiError {
  return caught instanceof ApiError ? caught : new ApiError(0, undefined);
}

/** Settings → Accounts: the banks, cards, wallets and cash the user's money is held in. */
export function AccountsSection() {
  const [showArchived, setShowArchived] = useState(false);
  const accounts = useAccounts(showArchived);
  const me = useMe();

  return (
    <SettingsSection
      title="Accounts"
      description="Where your money is held. Archive one you no longer use: it stays on past entries but can't be picked for new ones."
    >
      <div className="flex flex-col gap-5">
        <label className="flex items-center gap-2 self-end text-sm text-ink-soft">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(event) => setShowArchived(event.target.checked)}
            className="size-4 accent-lavender-deep"
          />
          Show archived
        </label>

        {accounts.isPending ? (
          <p className="text-sm text-ink-faint">Loading accounts…</p>
        ) : accounts.isError ? (
          <p role="alert" className="text-sm text-danger">
            {asApiError(accounts.error).message}
          </p>
        ) : accounts.data.length === 0 ? (
          <p className="text-sm text-ink-faint">No accounts yet. Add your bank, card, wallet or cash below.</p>
        ) : (
          <ul className="-my-3 divide-y divide-line">
            {accounts.data.map((account) => (
              <AccountRow key={account.id} account={account} />
            ))}
          </ul>
        )}

        {/* Keyed by the base currency: the page stays alive (<Activity>) and the currency picker
            only reads its default when mounted, so a base-currency change in Profile starts a fresh form. */}
        {me.data ? (
          <AddAccountForm key={me.data.profile.baseCurrency} baseCurrency={me.data.profile.baseCurrency} />
        ) : null}
      </div>
    </SettingsSection>
  );
}

/** Sends one change to an account, then refreshes every account list. Throws `ApiError`. */
function useUpdateAccount() {
  const queryClient = useQueryClient();
  return async (accountId: string, change: AccountUpdate) => {
    await unwrap<AccountView>(
      api.PATCH("/api/v1/accounts/{account_id}", {
        params: { path: { account_id: accountId } },
        body: change,
      }),
    );
    await invalidateAccounts(queryClient);
  };
}

/** One account: its name, kind and currency, or an inline form while it is being edited. */
function AccountRow({ account }: { account: AccountView }) {
  const updateAccount = useUpdateAccount();
  const toast = useToast();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);

  async function toggleArchived() {
    setBusy(true);
    try {
      await updateAccount(account.id, { isArchived: !account.isArchived });
      toast(account.isArchived ? `${account.name} is back in use` : `${account.name} archived`);
    } catch (caught) {
      toast(asApiError(caught).message, { tone: "error" });
    } finally {
      setBusy(false);
    }
  }

  if (editing) {
    return (
      <li className="py-3">
        <EditAccountForm account={account} onDone={() => setEditing(false)} />
      </li>
    );
  }

  return (
    <li className="flex items-center gap-3 py-3">
      <div className={`min-w-0 flex-1 ${account.isArchived ? "opacity-60" : ""}`}>
        <p className="truncate font-medium">{account.name}</p>
        <p className="text-xs text-ink-faint">
          {kindLabel(account.kind)} · {account.currency}
        </p>
      </div>
      {account.isArchived ? (
        <span className="rounded-full bg-paper px-2 py-0.5 text-xs text-ink-faint">Archived</span>
      ) : null}
      <button
        type="button"
        onClick={() => setEditing(true)}
        className="rounded-lg p-1.5 text-ink-faint hover:bg-lavender-wash hover:text-ink"
        aria-label={`Edit ${account.name}`}
        title="Rename or change kind"
      >
        <Pencil className="size-4" aria-hidden />
      </button>
      <Button
        size="sm"
        variant="ghost"
        busy={busy}
        onClick={toggleArchived}
        icon={account.isArchived ? <ArchiveRestore className="size-4" aria-hidden /> : <Archive className="size-4" aria-hidden />}
      >
        {account.isArchived ? "Unarchive" : "Archive"}
      </Button>
    </li>
  );
}

/** Rename or re-kind an account in place. The currency is fixed, so it is not offered. */
function EditAccountForm({ account, onDone }: { account: AccountView; onDone: () => void }) {
  const updateAccount = useUpdateAccount();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      await updateAccount(account.id, {
        name: String(form.get("name") ?? "").trim(),
        kind: String(form.get("kind")) as AccountKind,
      });
      onDone();
    } catch (caught) {
      setError(asApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-2">
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input name="name" aria-label="Account name" defaultValue={account.name} maxLength={60} required autoFocus />
        <Select name="kind" aria-label="Kind" defaultValue={account.kind} className="sm:w-44">
          {KINDS.map((kind) => (
            <option key={kind.value} value={kind.value}>
              {kind.label}
            </option>
          ))}
        </Select>
      </div>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error.message}
        </p>
      ) : null}
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
        <Button size="sm" type="submit" variant="primary" busy={busy}>
          Save
        </Button>
      </div>
    </form>
  );
}

/** The main (base) currency first, since it is the default, then the other offered ones. */
function currencyChoices(baseCurrency: string): { code: string; name: string }[] {
  const names = new Map<string, string>(CURRENCIES);
  const others = CURRENCIES.map(([code]) => code).filter((code) => code !== baseCurrency);
  return [baseCurrency, ...others].map((code) => ({ code, name: names.get(code) ?? code }));
}

/** Adds an account. Its currency starts at the user's base currency and is fixed once saved. */
function AddAccountForm({ baseCurrency }: { baseCurrency: string }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    setBusy(true);
    setError(null);
    try {
      const created = await unwrap<AccountView>(
        api.POST("/api/v1/accounts", {
          body: {
            name: String(form.get("name") ?? "").trim(),
            kind: String(form.get("kind")) as AccountKind,
            currency: String(form.get("currency")),
          },
        }),
      );
      await invalidateAccounts(queryClient);
      formElement.reset();
      toast(`${created.name} added`);
    } catch (caught) {
      setError(asApiError(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4 border-t border-line pt-5">
      <h3 className="font-medium">Add an account</h3>
      <Field label="Name">
        {({ id }) => <Input id={id} name="name" placeholder="HDFC Savings" maxLength={60} required />}
      </Field>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Kind">
          {({ id }) => (
            <Select id={id} name="kind" defaultValue="bank">
              {KINDS.map((kind) => (
                <option key={kind.value} value={kind.value}>
                  {kind.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Currency" hint="Can't be changed once the account is added.">
          {({ id, describedBy }) => (
            <Select id={id} name="currency" defaultValue={baseCurrency} aria-describedby={describedBy}>
              {currencyChoices(baseCurrency).map(({ code, name }) => (
                <option key={code} value={code}>
                  {code}: {name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      {error ? (
        <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
          {error.message}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" busy={busy} icon={<Plus className="size-4" aria-hidden />}>
          Add account
        </Button>
      </div>
    </form>
  );
}
