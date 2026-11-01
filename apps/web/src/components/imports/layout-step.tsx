"use client";

import type { ColumnMap, ImportDetail } from "@moneymoney/contracts";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Select } from "@/components/ui/field";

type AmountStyle = "single" | "split";

const NONE = "";

function columnLabel(header: string, index: number): string {
  return `${index + 1}. ${header.trim() || "(no name)"}`;
}

/** A column picker: the file's headers, plus "None" when the column is optional. */
function ColumnSelect({
  id,
  value,
  headers,
  optional = false,
  onChange,
}: {
  id: string;
  value: number | null;
  headers: string[];
  optional?: boolean;
  onChange: (value: number | null) => void;
}) {
  return (
    <Select id={id} value={value === null ? NONE : String(value)} onChange={(event) => onChange(event.target.value === NONE ? null : Number(event.target.value))}>
      <option value={NONE}>{optional ? "None" : "Choose a column"}</option>
      {headers.map((header, index) => (
        <option key={index} value={index}>
          {columnLabel(header, index)}
        </option>
      ))}
    </Select>
  );
}

/**
 * Confirm which column is which. MoneyMoney guesses from the header names; the user checks the
 * guess against the first rows of the file once, and it is remembered for the account.
 */
export function LayoutStep({
  detail,
  busy,
  error,
  onConfirm,
}: {
  detail: ImportDetail;
  busy: boolean;
  error: string | null;
  onConfirm: (layout: ColumnMap) => void;
}) {
  const [layout, setLayout] = useState<ColumnMap>(detail.layout);
  const [amountStyle, setAmountStyle] = useState<AmountStyle>(
    detail.layout.amountColumn === null && detail.layout.debitColumn !== null ? "split" : "single",
  );
  const set = (change: Partial<ColumnMap>) => setLayout((current) => ({ ...current, ...change }));

  function submit() {
    // Only the columns of the chosen amount style are sent, so a stale pick never leaks in.
    onConfirm(
      amountStyle === "single"
        ? { ...layout, debitColumn: null, creditColumn: null }
        : { ...layout, amountColumn: null },
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-ink-soft">
        {detail.layoutConfirmed
          ? "Change which columns MoneyMoney reads."
          : "Check that MoneyMoney read your file correctly. You only do this once for this account."}
      </p>

      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-left text-xs">
          <caption className="sr-only">The first rows of your file</caption>
          <thead className="bg-paper/70 text-ink-faint">
            <tr>
              {detail.headers.map((header, index) => (
                <th key={index} scope="col" className="px-3 py-2 font-semibold whitespace-nowrap">
                  {header || `Column ${index + 1}`}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {detail.sampleRows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {detail.headers.map((_, index) => (
                  <td key={index} className="px-3 py-1.5 whitespace-nowrap text-ink-soft">
                    {row[index] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Date column">
          {({ id }) => <ColumnSelect id={id} value={layout.dateColumn ?? null} headers={detail.headers} onChange={(dateColumn) => set({ dateColumn })} />}
        </Field>
        <Field label="Dates are written" hint="03/04/2026 is 3 April when day first.">
          {({ id }) => (
            <Select id={id} value={layout.dateOrder} onChange={(event) => set({ dateOrder: event.target.value as ColumnMap["dateOrder"] })}>
              <option value="day_first">Day first (03/04/2026 = 3 April)</option>
              <option value="month_first">Month first (03/04/2026 = 4 March)</option>
            </Select>
          )}
        </Field>
        <Field label="Description column">
          {({ id }) => <ColumnSelect id={id} value={layout.descriptionColumn ?? null} headers={detail.headers} optional onChange={(descriptionColumn) => set({ descriptionColumn })} />}
        </Field>
        <Field label="Amounts are in">
          {({ id }) => (
            <Select id={id} value={amountStyle} onChange={(event) => setAmountStyle(event.target.value as AmountStyle)}>
              <option value="single">One column (money out is negative or marked Dr)</option>
              <option value="split">Separate debit and credit columns</option>
            </Select>
          )}
        </Field>
        {amountStyle === "single" ? (
          <Field label="Amount column">
            {({ id }) => <ColumnSelect id={id} value={layout.amountColumn ?? null} headers={detail.headers} onChange={(amountColumn) => set({ amountColumn })} />}
          </Field>
        ) : (
          <>
            <Field label="Debit column (money out)">
              {({ id }) => <ColumnSelect id={id} value={layout.debitColumn ?? null} headers={detail.headers} onChange={(debitColumn) => set({ debitColumn })} />}
            </Field>
            <Field label="Credit column (money in)">
              {({ id }) => <ColumnSelect id={id} value={layout.creditColumn ?? null} headers={detail.headers} onChange={(creditColumn) => set({ creditColumn })} />}
            </Field>
          </>
        )}
      </div>

      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button variant="primary" busy={busy} onClick={submit}>
          Use these columns
        </Button>
      </div>
    </div>
  );
}
