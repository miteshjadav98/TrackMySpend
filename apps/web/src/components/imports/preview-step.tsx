"use client";

import type { CategoryView, ImportDetail, PreviewRow, RowChange, RowStatus } from "@moneymoney/contracts";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";
import { formatMinor } from "@/lib/format";

const STATUS_FILTERS: { value: RowStatus | ""; label: string }[] = [
  { value: "", label: "All rows" },
  { value: "to_import", label: "To import" },
  { value: "skipped", label: "Skipped" },
  { value: "likely_duplicate", label: "Likely duplicates" },
  { value: "transfer", label: "Transfers" },
];

const SOURCE_NOTES: Record<string, string> = {
  rule: "From your merchant rule",
  ai: "Suggested",
  keyword: "Guessed from the wording",
  user: "Your pick",
};

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-xl border border-line bg-paper/60 px-3 py-2">
      <p className="figure text-lg font-semibold">{value}</p>
      <p className="text-xs text-ink-faint">{label}</p>
    </div>
  );
}

/** The preview: counts, a filterable table with a tick and a category per row, and the import button. */
export function PreviewStep({
  detail,
  categories,
  statusFilter,
  onStatusFilter,
  onChangeRows,
  onShowMore,
  onChangeColumns,
  onConfirm,
  busy,
  error,
}: {
  detail: ImportDetail;
  categories: CategoryView[];
  statusFilter: RowStatus | "";
  onStatusFilter: (status: RowStatus | "") => void;
  onChangeRows: (changes: RowChange[]) => void;
  onShowMore: () => void;
  onChangeColumns: () => void;
  onConfirm: () => void;
  busy: boolean;
  error: string | null;
}) {
  const { counts } = detail;
  const selectable = detail.rows.filter((row) => row.status !== "skipped");
  const allTicked = selectable.length > 0 && selectable.every((row) => row.isSelected);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Count label="To import" value={counts.toImport} />
          <Count label="Skipped" value={counts.skipped} />
          <Count label="Likely duplicates" value={counts.likelyDuplicates} />
          <Count label="Transfers" value={counts.transfers} />
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="import-filter" className="sr-only">
            Show rows
          </label>
          <Select id="import-filter" value={statusFilter} onChange={(event) => onStatusFilter(event.target.value as RowStatus | "")}>
            {STATUS_FILTERS.map((filter) => (
              <option key={filter.value} value={filter.value}>
                {filter.label}
              </option>
            ))}
          </Select>
          <Button size="sm" onClick={onChangeColumns}>
            Change columns
          </Button>
        </div>
      </div>

      <div className="overflow-x-auto rounded-xl border border-line">
        <table className="w-full text-left text-sm">
          <caption className="sr-only">Statement rows to import</caption>
          <thead className="border-b border-line bg-paper/70 text-xs tracking-wide text-ink-faint uppercase">
            <tr>
              <th scope="col" className="w-10 px-3 py-2">
                <input
                  type="checkbox"
                  aria-label="Tick or untick every row shown"
                  className="size-4 accent-lavender-deep"
                  checked={allTicked}
                  disabled={selectable.length === 0}
                  onChange={(event) =>
                    onChangeRows(selectable.map((row) => ({ id: row.id, isSelected: event.target.checked })))
                  }
                />
              </th>
              <th scope="col" className="px-3 py-2 font-semibold">Date</th>
              <th scope="col" className="px-3 py-2 font-semibold">Description</th>
              <th scope="col" className="px-3 py-2 font-semibold">Category</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Amount</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {detail.rows.map((row) => (
              <Row key={row.id} row={row} categories={categories} onChange={(change) => onChangeRows([change])} />
            ))}
            {detail.rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-8 text-center text-ink-faint">
                  No rows match this filter.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      {detail.rows.length < detail.rowsTotal ? (
        <div className="flex justify-center">
          <Button size="sm" onClick={onShowMore}>
            Show more ({detail.rowsTotal - detail.rows.length} left)
          </Button>
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <p className="text-sm text-ink-soft">
          {counts.selected} selected · out {formatMinor(counts.selectedOutMinor, detail.currency)} · in{" "}
          {formatMinor(counts.selectedInMinor, detail.currency)}
        </p>
        <Button variant="primary" busy={busy} disabled={counts.selected === 0} onClick={onConfirm}>
          {counts.selected === 1 ? "Import 1 row" : `Import ${counts.selected} rows`}
        </Button>
      </div>
    </div>
  );
}

function Row({
  row,
  categories,
  onChange,
}: {
  row: PreviewRow;
  categories: CategoryView[];
  onChange: (change: RowChange) => void;
}) {
  const skipped = row.status === "skipped";
  const kind = row.direction === "in" ? "income" : "expense";
  const options = categories.filter((category) => category.kind === kind);
  const note = row.categorySource ? SOURCE_NOTES[row.categorySource] : null;
  return (
    <tr className={skipped ? "text-ink-faint" : undefined}>
      <td className="px-3 py-2">
        <input
          type="checkbox"
          className="size-4 accent-lavender-deep"
          aria-label={`Import row ${row.position}`}
          checked={row.isSelected}
          disabled={skipped}
          onChange={(event) => onChange({ id: row.id, isSelected: event.target.checked })}
        />
      </td>
      <td className="px-3 py-2 whitespace-nowrap">{row.occurredOn ?? "—"}</td>
      <td className="max-w-[22rem] px-3 py-2">
        <span className="block truncate" title={row.description ?? undefined}>
          {row.description ?? "—"}
        </span>
        {row.note ? <span className="block text-xs">{row.note}</span> : null}
      </td>
      <td className="px-3 py-2">
        {row.category && !skipped ? (
          <>
            <label className="sr-only" htmlFor={`category-${row.id}`}>
              Category for row {row.position}
            </label>
            <Select
              id={`category-${row.id}`}
              className="h-8 min-w-40 text-sm"
              value={row.category.id}
              onChange={(event) => onChange({ id: row.id, categoryId: event.target.value })}
            >
              {options.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </Select>
            {note ? <span className="block text-xs text-ink-faint">{note}</span> : null}
          </>
        ) : null}
      </td>
      <td className={`figure px-3 py-2 text-right font-semibold whitespace-nowrap ${row.direction === "in" ? "text-income" : ""}`}>
        {row.amountFormatted ? `${row.direction === "in" ? "+" : "-"}${row.amountFormatted}` : "—"}
      </td>
    </tr>
  );
}
