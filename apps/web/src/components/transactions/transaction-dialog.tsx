"use client";

import type {
  AccountRef,
  AccountView,
  CategoryView,
  TransactionCreate,
  TransactionType,
  TransactionUpdate,
  TransactionView,
} from "@moneymoney/contracts";
import { type FormEvent, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, newKey, unwrap } from "@/lib/api";
import { accountOptionLabel, PAYMENT_METHODS, todayISO } from "@/lib/format";
import { invalidateLedger, useAccounts, useCategories, useMe, useQueryClient } from "@/lib/queries";

const CURRENCIES = ["INR", "USD", "EUR", "GBP", "AED", "SGD", "AUD", "CAD", "JPY"];

const FIELD_FOR_ERROR: Record<string, string> = {
  amount: "amount",
  occurredOn: "occurredOn",
  currency: "currency",
  categoryId: "categoryId",
  accountId: "accountId",
  toAccountId: "toAccountId",
};

const TYPE_LABELS: Record<TransactionType, string> = {
  expense: "Money out",
  income: "Money in",
  transfer: "Transfer",
};

/**
 * The accounts the picker offers: every active account, plus the transaction's current one
 * if it has since been archived (an edit may keep it, but nobody can pick it anew).
 */
function accountChoices(accounts: AccountView[], current: AccountRef | null): { id: string; label: string }[] {
  const choices = accounts
    .filter((account) => !account.isArchived || account.id === current?.id)
    .map((account) => ({ id: account.id, label: accountOptionLabel(account) }));
  // Until the list has loaded, still show the account the transaction already has.
  if (current && !choices.some((choice) => choice.id === current.id)) {
    choices.unshift({ id: current.id, label: current.name });
  }
  return choices;
}

/** Add or edit a transaction by hand. The same server validation as chat applies. */
export function TransactionDialog({
  open,
  onClose,
  transaction,
}: {
  open: boolean;
  onClose: () => void;
  transaction?: TransactionView | null;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={transaction ? "Edit transaction" : "Add a transaction"}
      description={transaction ? undefined : "Or just tell the assistant in chat."}
    >
      {open ? <TransactionForm key={transaction?.id ?? "new"} transaction={transaction} onDone={onClose} /> : null}
    </Dialog>
  );
}

function TransactionForm({
  transaction,
  onDone,
}: {
  transaction?: TransactionView | null;
  onDone: () => void;
}) {
  const me = useMe();
  const categories = useCategories();
  const accounts = useAccounts(true);
  const queryClient = useQueryClient();
  const toast = useToast();
  const [idempotencyKey] = useState(newKey);
  const [type, setType] = useState<TransactionType>(transaction?.type ?? "expense");
  const [categoryId, setCategoryId] = useState<string>(transaction?.category?.id ?? "");
  const [accountId, setAccountId] = useState<string>(transaction?.account?.id ?? "");
  const [toAccountId, setToAccountId] = useState<string>(transaction?.toAccount?.id ?? "");
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const options = useMemo(
    () => (categories.data ?? []).filter((c: CategoryView) => c.kind === type),
    [categories.data, type],
  );
  const currentAccount = transaction?.account ?? null;
  const accountOptions = useMemo(
    () => accountChoices(accounts.data ?? [], currentAccount),
    [accounts.data, currentAccount],
  );
  const toAccountOptions = useMemo(
    () => accountChoices(accounts.data ?? [], transaction?.toAccount ?? null).filter((choice) => choice.id !== accountId),
    [accounts.data, transaction?.toAccount, accountId],
  );
  const baseCurrency = me.data?.profile.baseCurrency ?? "INR";
  const [currency, setCurrency] = useState<string>(transaction?.currency ?? baseCurrency);
  const isTransfer = type === "transfer";

  // A transfer lives in its accounts' currency, so picking the source account sets it.
  function pickFromAccount(id: string) {
    setAccountId(id);
    if (id === toAccountId) setToAccountId(""); // the two ends can't be the same account
    const picked = (accounts.data ?? []).find((account) => account.id === id);
    if (isTransfer && picked) setCurrency(picked.currency);
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const text = (name: string) => {
      const value = String(form.get(name) ?? "").trim();
      return value === "" ? null : value;
    };
    const body = {
      type,
      amount: String(form.get("amount") ?? "").replace(/,/g, "").trim(),
      currency,
      occurredOn: String(form.get("occurredOn") ?? todayISO()),
      categoryId: isTransfer ? null : categoryId || null,
      accountId: accountId || null,
      toAccountId: isTransfer ? toAccountId || null : null,
      description: text("description"),
      merchant: text("merchant"),
      paymentMethod: (text("paymentMethod") as TransactionCreate["paymentMethod"]) ?? null,
      notes: text("notes"),
    };
    setBusy(true);
    setError(null);
    try {
      if (transaction) {
        const update: TransactionUpdate = { version: transaction.version, ...body };
        await unwrap(
          api.PATCH("/api/v1/transactions/{transaction_id}", {
            params: { path: { transaction_id: transaction.id } },
            body: update,
          }),
        );
        toast("Changes saved");
      } else {
        await unwrap(
          api.POST("/api/v1/transactions", {
            body,
            params: { header: { "Idempotency-Key": idempotencyKey } },
          }),
        );
        toast("Transaction added");
      }
      await invalidateLedger(queryClient);
      onDone();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
      setBusy(false);
    }
  }

  async function onDelete() {
    if (!transaction) return;
    setBusy(true);
    try {
      await unwrap(
        api.DELETE("/api/v1/transactions/{transaction_id}", {
          params: { path: { transaction_id: transaction.id } },
        }),
      );
      await invalidateLedger(queryClient);
      toast("Transaction deleted", {
        action: {
          label: "Undo",
          onClick: async () => {
            await api.POST("/api/v1/transactions/{transaction_id}/restore", {
              params: { path: { transaction_id: transaction.id } },
            });
            await invalidateLedger(queryClient);
          },
        },
      });
      onDone();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
      setBusy(false);
    }
  }

  const fieldError = (name: string) =>
    error && FIELD_FOR_ERROR[error.field ?? ""] === name ? error.message : null;
  const generalError = error && !fieldError(error.field ?? "") ? error : null;

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <fieldset className="grid grid-cols-3 gap-2">
        <legend className="sr-only">Type</legend>
        {(["expense", "income", "transfer"] as const).map((value) => (
          <label
            key={value}
            className={`flex cursor-pointer items-center justify-center rounded-[10px] border px-3 py-2 text-[15px] font-medium transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-lavender-deep ${
              type === value
                ? value === "income"
                  ? "border-income bg-income-wash text-income"
                  : "border-lavender-deep bg-lavender-wash text-lavender-ink"
                : "border-line-strong text-ink-soft hover:border-lavender"
            }`}
          >
            <input
              type="radio"
              name="type"
              value={value}
              checked={type === value}
              onChange={() => {
                setType(value);
                setCategoryId("");
              }}
              className="sr-only"
            />
            {TYPE_LABELS[value]}
          </label>
        ))}
      </fieldset>

      <div className="grid grid-cols-[1fr_7rem] gap-3">
        <Field label="Amount" error={fieldError("amount")}>
          {({ id, invalid, describedBy }) => (
            <Input
              id={id}
              name="amount"
              inputMode="decimal"
              required
              autoFocus={!transaction}
              defaultValue={transaction ? String(transaction.amount) : ""}
              placeholder="350"
              pattern="[0-9.,]+"
              aria-invalid={invalid}
              aria-describedby={describedBy}
              className="figure text-lg"
            />
          )}
        </Field>
        <Field label="Currency" error={fieldError("currency")}>
          {({ id }) => (
            <Select id={id} name="currency" value={currency} onChange={(event) => setCurrency(event.target.value)}>
              {Array.from(new Set([baseCurrency, ...CURRENCIES])).map((code) => (
                <option key={code}>{code}</option>
              ))}
            </Select>
          )}
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <Field label="Date" error={fieldError("occurredOn")}>
          {({ id, invalid }) => (
            <Input
              id={id}
              name="occurredOn"
              type="date"
              required
              max={todayISO()}
              defaultValue={transaction?.occurredOn ?? todayISO()}
              aria-invalid={invalid}
            />
          )}
        </Field>
        {isTransfer ? null : (
          <Field label="Category" error={fieldError("categoryId")}>
            {({ id }) => (
              <Select id={id} value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
                <option value="">Uncategorised</option>
                {options.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
      </div>

      <Field label="What was it for?">
        {({ id }) => (
          <Input
            id={id}
            name="description"
            maxLength={500}
            defaultValue={transaction?.description ?? ""}
            placeholder="Dinner with friends"
          />
        )}
      </Field>

      {isTransfer ? null : (
        <Field label="Paid to / from">
          {({ id }) => (
            <Input
              id={id}
              name="merchant"
              maxLength={200}
              defaultValue={transaction?.merchant ?? ""}
              placeholder="Swiggy"
            />
          )}
        </Field>
      )}

      <div className="grid grid-cols-2 gap-3">
        <Field
          label={isTransfer ? "From account" : type === "income" ? "Into account" : "From account"}
          error={fieldError("accountId")}
        >
          {({ id, invalid, describedBy }) => (
            <Select
              id={id}
              value={accountId}
              onChange={(event) => pickFromAccount(event.target.value)}
              required={isTransfer}
              aria-invalid={invalid}
              aria-describedby={describedBy}
            >
              <option value="">{isTransfer ? "Choose an account" : "No account"}</option>
              {accountOptions.map((choice) => (
                <option key={choice.id} value={choice.id}>
                  {choice.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        {isTransfer ? (
          <Field label="To account" error={fieldError("toAccountId")}>
            {({ id, invalid, describedBy }) => (
              <Select
                id={id}
                value={toAccountId}
                onChange={(event) => setToAccountId(event.target.value)}
                required
                aria-invalid={invalid}
                aria-describedby={describedBy}
              >
                <option value="">Choose an account</option>
                {toAccountOptions.map((choice) => (
                  <option key={choice.id} value={choice.id}>
                    {choice.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        ) : (
          <Field label="Payment method">
            {({ id }) => (
              <Select id={id} name="paymentMethod" defaultValue={transaction?.paymentMethod ?? ""}>
                <option value="">Not set</option>
                {PAYMENT_METHODS.map((method) => (
                  <option key={method.value} value={method.value}>
                    {method.label}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}
      </div>

      <Field label="Notes">
        {({ id }) => (
          <textarea
            id={id}
            name="notes"
            maxLength={1000}
            rows={2}
            defaultValue={transaction?.notes ?? ""}
            className="w-full rounded-[10px] border border-line-strong bg-surface px-3 py-2 text-[15px] focus:border-lavender-deep focus:ring-2 focus:ring-lavender/30 focus:outline-none"
          />
        )}
      </Field>

      {generalError ? (
        <div role="alert" className="flex items-center justify-between gap-3 rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
          <span>{generalError.message}</span>
          {generalError.code === "version_conflict" ? (
            <Button
              size="sm"
              onClick={async () => {
                await invalidateLedger(queryClient);
                onDone();
              }}
            >
              Reload
            </Button>
          ) : null}
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-2 pt-1">
        {transaction ? (
          confirmDelete ? (
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
          )
        ) : (
          <span />
        )}
        <div className="flex gap-2">
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" busy={busy}>
            {transaction ? "Save changes" : "Add transaction"}
          </Button>
        </div>
      </div>
    </form>
  );
}
