"use client";

import type { AccountView } from "@moneymoney/contracts";
import { useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { formatMinor } from "@/lib/format";
import { invalidateAccounts, useMe, useQueryClient } from "@/lib/queries";
import { reportToday } from "@/lib/report-filters";

export function AnchorEditor({ account, close }: { account: AccountView; close: () => void }) {
  const me = useMe().data;
  const today = reportToday(me?.profile.timezone ?? "UTC");
  const digits = new Intl.NumberFormat("en", { style: "currency", currency: account.currency }).resolvedOptions().maximumFractionDigits ?? 2;
  const anchor = account.balanceAnchor;
  const [version] = useState(account.updatedAt);
  const [amount, setAmount] = useState(anchor ? (Math.abs(anchor.amountMinor) / 10 ** digits).toFixed(digits) : "");
  const [asOf, setAsOf] = useState(anchor?.asOf ?? today);
  const [negative, setNegative] = useState((anchor?.amountMinor ?? 0) < 0);
  const [review, setReview] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const client = useQueryClient();
  const toast = useToast();
  const liability = account.kind === "credit_card" || account.kind === "loan";
  const positiveLabel = liability ? "Amount owed" : "Money held";
  const negativeLabel = liability ? "Credit balance" : "Overdraft";

  function preview(event: FormEvent) {
    event.preventDefault();
    const [whole, fraction = ""] = amount.trim().split(".");
    if (!/^\d+(\.\d+)?$/.test(amount.trim()) || fraction.length > digits) {
      setError(`Enter an amount in ${account.currency} with up to ${digits} decimal places.`);
      return;
    }
    const minor = Number(whole + fraction.padEnd(digits, "0"));
    if (!Number.isSafeInteger(minor) || minor > 1e15) {
      setError("The opening balance exceeds the supported amount.");
      return;
    }
    setError("");
    setReview(negative ? -minor : minor);
  }

  async function save() {
    if (review === null || busy) return;
    setBusy(true);
    try {
      await unwrap(api.PATCH("/api/v1/accounts/{account_id}", {
        params: { path: { account_id: account.id } },
        body: { expectedUpdatedAt: version, balanceAnchor: { asOf, amountMinor: review } },
      }));
      await invalidateAccounts(client);
      toast("Opening balance saved");
      close();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        await invalidateAccounts(client);
        setError("This account changed. Close and reopen the editor to review its latest balance.");
      } else setError((caught as Error).message);
    } finally { setBusy(false); }
  }

  return <Dialog open onClose={() => { if (!busy) close(); }} title={review === null ? "Opening balance" : "Confirm opening balance"} description={account.name}>
    {review === null ? <form className="grid gap-4" onSubmit={preview}>
      <label>Balance type<Select value={negative ? "negative" : "positive"} onChange={e => setNegative(e.target.value === "negative")}>
        <option value="positive">{positiveLabel}</option><option value="negative">{negativeLabel}</option>
      </Select></label>
      <label>Amount ({account.currency})<Input required inputMode="decimal" maxLength={24} value={amount} onChange={e => setAmount(e.target.value)} /></label>
      <label>At start of day<Input required type="date" max={today} value={asOf} onChange={e => setAsOf(e.target.value)} /></label>
      <Button variant="primary" type="submit">Review opening balance</Button>
    </form> : <div className="grid gap-4">
      <p>{review < 0 ? negativeLabel : positiveLabel} at the start of {asOf}: <strong>{formatMinor(Math.abs(review), account.currency, me?.profile.locale)}</strong>.</p>
      <p className="text-sm text-ink-soft">Movements dated {asOf} and later will count toward this balance.</p>
      <div className="flex gap-2"><Button disabled={busy} onClick={() => { setReview(null); setError(""); }}>Edit</Button><Button variant="primary" busy={busy} onClick={save}>Confirm and save</Button></div>
    </div>}
    {error && <p role="alert" className="mt-3 text-danger">{error}</p>}
  </Dialog>;
}
