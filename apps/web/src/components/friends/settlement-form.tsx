"use client";

import type { FriendView, SettlementCreated } from "@moneymoney/contracts";
import { HandCoins } from "lucide-react";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { accountOptionLabel, CURRENCIES, todayISO } from "@/lib/format";
import { invalidateFriends, useAccounts, useMe, useQueryClient } from "@/lib/queries";

/**
 * "Record settlement": money that changed hands with this friend, in either direction. It
 * moves the balance only; it is never spending or income. A payment larger than what was owed
 * is saved, and the reply's warning is shown so the user can check it.
 */
export function SettlementForm({ friend }: { friend: FriendView }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const me = useMe();
  const accounts = useAccounts();
  const [error, setError] = useState<ApiError | null>(null);
  const [warning, setWarning] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const baseCurrency = me.data?.profile.baseCurrency ?? "INR";

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const accountId = String(form.get("accountId") ?? "");
    const note = String(form.get("note") ?? "").trim();
    setBusy(true);
    setError(null);
    setWarning(null);
    try {
      const saved = await unwrap<SettlementCreated>(
        api.POST("/api/v1/settlements", {
          body: {
            friendId: friend.id,
            direction: String(form.get("direction")) === "you_paid_friend" ? "you_paid_friend" : "friend_paid_you",
            amount: String(form.get("amount") ?? "").trim(),
            currency: String(form.get("currency") ?? baseCurrency),
            occurredOn: String(form.get("occurredOn") ?? "") || null,
            accountId: accountId || null,
            note: note || null,
          },
        }),
      );
      await invalidateFriends(queryClient);
      formElement.reset();
      if (saved.warning) setWarning(saved.warning);
      toast(`Recorded ${saved.amountFormatted}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="flex flex-col gap-4 rounded-[var(--radius-card)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]"
    >
      <h2 className="display text-lg font-semibold">Record settlement</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Who paid">
          {({ id }) => (
            <Select id={id} name="direction" defaultValue="friend_paid_you">
              <option value="friend_paid_you">{friend.name} paid me</option>
              <option value="you_paid_friend">I paid {friend.name}</option>
            </Select>
          )}
        </Field>
        <Field label="Amount">
          {({ id }) => <Input id={id} name="amount" inputMode="decimal" placeholder="500" required />}
        </Field>
        <Field label="Currency">
          {({ id }) => (
            <Select id={id} name="currency" key={baseCurrency} defaultValue={baseCurrency}>
              {CURRENCIES.map(([code, name]) => (
                <option key={code} value={code}>
                  {code} · {name}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Date">
          {({ id }) => <Input id={id} name="occurredOn" type="date" defaultValue={todayISO()} max={todayISO()} />}
        </Field>
        <Field label="Account (optional)" hint="Where the money went, or came from.">
          {({ id, describedBy }) => (
            <Select id={id} name="accountId" defaultValue="" aria-describedby={describedBy}>
              <option value="">No account</option>
              {accounts.data?.map((account) => (
                <option key={account.id} value={account.id}>
                  {accountOptionLabel(account)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <Field label="Note (optional)">
          {({ id }) => <Input id={id} name="note" maxLength={500} placeholder="UPI" />}
        </Field>
      </div>
      {error ? (
        <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
          {error.message}
        </p>
      ) : null}
      {warning ? (
        <p role="status" className="rounded-[10px] bg-turmeric-wash px-3 py-2 text-sm text-turmeric-ink">
          {warning}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" busy={busy} icon={<HandCoins className="size-4" aria-hidden />}>
          Record settlement
        </Button>
      </div>
    </form>
  );
}
