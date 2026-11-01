"use client";

import type { SharedExpenseUpdate, SharedExpenseView } from "@moneymoney/contracts";
import { type FormEvent, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { formatDay, todayISO } from "@/lib/format";
import { invalidateLedger, useFriends, useMe, useQueryClient, useSharedExpense } from "@/lib/queries";
import { SplitFields, type SplitState, splitParticipants, splitProblem } from "./split-fields";

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY"];

/** A shared expense's total, payer and every share, with edit and delete for the recorder. */
export function SharedExpenseDialog({
  sharedExpenseId,
  onClose,
}: {
  sharedExpenseId: string | null;
  onClose: () => void;
}) {
  return (
    <Dialog
      open={sharedExpenseId !== null}
      onClose={onClose}
      title="Shared expense"
      description="Only your share counts in your spending."
    >
      {sharedExpenseId ? <SharedExpenseBody key={sharedExpenseId} id={sharedExpenseId} onDone={onClose} /> : null}
    </Dialog>
  );
}

function SharedExpenseBody({ id, onDone }: { id: string; onDone: () => void }) {
  const shared = useSharedExpense(id);
  const [editing, setEditing] = useState(false);
  if (shared.isPending) return <p className="text-sm text-ink-faint">Loading…</p>;
  if (shared.isError) {
    return (
      <p role="alert" className="text-sm text-danger">
        {shared.error.message}
      </p>
    );
  }
  return editing ? (
    <EditForm shared={shared.data} onCancel={() => setEditing(false)} onSaved={() => setEditing(false)} />
  ) : (
    <Details shared={shared.data} onEdit={() => setEditing(true)} onDeleted={onDone} />
  );
}

function Details({
  shared,
  onEdit,
  onDeleted,
}: {
  shared: SharedExpenseView;
  onEdit: () => void;
  onDeleted: () => void;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onDelete() {
    setBusy(true);
    try {
      await unwrap<unknown>(
        api.DELETE("/api/v1/shared-expenses/{shared_expense_id}", {
          params: { path: { shared_expense_id: shared.id } },
        }),
      );
      await invalidateLedger(queryClient);
      toast("Shared expense deleted");
      onDeleted();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Couldn't delete it.");
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="display text-xl font-semibold">{shared.description ?? shared.merchant ?? "Shared expense"}</p>
        <p className="text-sm text-ink-soft">
          {formatDay(shared.occurredOn)}
          {shared.merchant && shared.description ? ` · ${shared.merchant}` : ""}
        </p>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <dt className="text-ink-faint">Total</dt>
          <dd className="figure text-lg font-semibold">{shared.totalFormatted}</dd>
        </div>
        <div>
          <dt className="text-ink-faint">Paid by</dt>
          <dd className="text-lg font-semibold">{shared.payer.name}</dd>
        </div>
      </dl>
      <table className="w-full text-left text-sm">
        <caption className="sr-only">Shares</caption>
        <thead className="text-xs tracking-wide text-ink-faint uppercase">
          <tr>
            <th scope="col" className="py-1.5 font-semibold">
              Person
            </th>
            <th scope="col" className="py-1.5 text-right font-semibold">
              Share
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-line border-t border-line">
          {shared.shares.map((share) => (
            <tr key={share.friendId ?? "you"}>
              <td className="py-2">{share.name}</td>
              <td className="figure py-2 text-right font-medium">{share.amountFormatted}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex items-center justify-between gap-2 pt-1">
        {confirmDelete ? (
          <div className="flex items-center gap-2">
            <Button variant="danger" size="sm" onClick={onDelete} busy={busy}>
              Delete it
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(false)}>
              Keep
            </Button>
          </div>
        ) : (
          <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)} className="text-danger">
            Delete
          </Button>
        )}
        <Button variant="primary" onClick={onEdit}>
          Edit
        </Button>
      </div>
    </div>
  );
}

/** Turn a stored shared expense back into the choices the split form edits. */
function splitFrom(shared: SharedExpenseView): SplitState {
  return {
    friendIds: shared.shares.flatMap((share) => (share.friendId ? [share.friendId] : [])),
    payerId: shared.payer.friendId ?? "",
    // The stored amounts are the truth, so editing starts from them as an exact split.
    kind: "exact",
    amounts: Object.fromEntries(shared.shares.map((share) => [share.friendId ?? "you", String(share.amount)])),
  };
}

function EditForm({
  shared,
  onCancel,
  onSaved,
}: {
  shared: SharedExpenseView;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const me = useMe();
  const friends = useFriends();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [total, setTotal] = useState(String(shared.total));
  const [currency, setCurrency] = useState(shared.currency);
  const [split, setSplit] = useState<SplitState>(() => splitFrom(shared));
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const names = Object.fromEntries(
    shared.shares.flatMap((share) => (share.friendId ? [[share.friendId, share.name]] : [])),
  );
  const baseCurrency = me.data?.profile.baseCurrency ?? "INR";
  const problem = splitProblem(split, total, currency);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim() || null;
    const body: SharedExpenseUpdate = {
      total: total.replace(/,/g, "").trim(),
      currency,
      occurredOn: String(form.get("occurredOn") ?? todayISO()),
      description: text("description"),
      merchant: text("merchant"),
      payerFriendId: split.payerId || null,
      split: split.kind,
      participants: splitParticipants(split),
    };
    setBusy(true);
    setError(null);
    try {
      await unwrap<SharedExpenseView>(
        api.PUT("/api/v1/shared-expenses/{shared_expense_id}", {
          params: { path: { shared_expense_id: shared.id } },
          body,
        }),
      );
      await invalidateLedger(queryClient);
      toast("Changes saved");
      onSaved();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <div className="grid grid-cols-[1fr_7rem] gap-3">
        <Field label="Total">
          {({ id }) => (
            <Input
              id={id}
              inputMode="decimal"
              required
              value={total}
              onChange={(event) => setTotal(event.target.value)}
              pattern="[0-9.,]+"
              className="figure text-lg"
            />
          )}
        </Field>
        <Field label="Currency">
          {({ id }) => (
            <Select id={id} value={currency} onChange={(event) => setCurrency(event.target.value)}>
              {Array.from(new Set([baseCurrency, shared.currency, ...CURRENCIES])).map((code) => (
                <option key={code}>{code}</option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <Field label="Date">
        {({ id }) => (
          <Input id={id} name="occurredOn" type="date" required max={todayISO()} defaultValue={shared.occurredOn} />
        )}
      </Field>
      <Field label="What was it for?">
        {({ id }) => <Input id={id} name="description" maxLength={500} defaultValue={shared.description ?? ""} />}
      </Field>
      <Field label="Paid to">
        {({ id }) => <Input id={id} name="merchant" maxLength={200} defaultValue={shared.merchant ?? ""} />}
      </Field>
      <SplitFields
        friends={friends.data ?? []}
        split={split}
        onChange={setSplit}
        total={total}
        currency={currency}
        names={names}
      />
      <p className="-mt-2 text-xs text-ink-faint">
        Your own category, account and notes are changed on your share in the transactions list.
      </p>
      {error ? (
        <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
          {error.message}
        </p>
      ) : null}
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" busy={busy} disabled={problem !== null}>
          Save changes
        </Button>
      </div>
    </form>
  );
}
