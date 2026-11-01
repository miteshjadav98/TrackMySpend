"use client";

import type { ImportSummary } from "@moneymoney/contracts";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { formatRelative } from "@/lib/format";
import { invalidateLedger, useImports, useQueryClient } from "@/lib/queries";

const STATUS_LABELS: Record<ImportSummary["status"], string> = {
  previewing: "Not saved yet",
  imported: "Imported",
  undone: "Undone",
};

/** Past statement imports, with Undo for saved ones and a way back into an unsaved preview. */
export function ImportsDialog({
  open,
  onClose,
  onReview,
}: {
  open: boolean;
  onClose: () => void;
  /** Open an unsaved preview in the import dialog. */
  onReview: (importId: string) => void;
}) {
  const imports = useImports(open);
  return (
    <Dialog open={open} onClose={onClose} title="Statement imports" description="Undo an import to remove everything it created.">
      {imports.isPending ? (
        <p className="py-6 text-center text-sm text-ink-faint">Loading imports…</p>
      ) : imports.isError ? (
        <p role="alert" className="py-6 text-center text-sm text-danger">
          {imports.error.message}
        </p>
      ) : imports.data.length === 0 ? (
        <p className="py-6 text-center text-sm text-ink-soft">No imports yet.</p>
      ) : (
        <ul className="divide-y divide-line">
          {imports.data.map((item) => (
            <ImportItem key={item.id} item={item} onReview={onReview} />
          ))}
        </ul>
      )}
    </Dialog>
  );
}

function ImportItem({ item, onReview }: { item: ImportSummary; onReview: (importId: string) => void }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);

  async function act(call: () => Promise<unknown>, message: string) {
    setBusy(true);
    try {
      await call();
      await invalidateLedger(queryClient);
      toast(message);
      setAsking(false);
    } catch (caught) {
      toast(caught instanceof ApiError ? caught.message : "That didn't work. Please try again.", { tone: "error" });
    } finally {
      setBusy(false);
    }
  }

  const undo = () =>
    act(() => unwrap(api.POST("/api/v1/imports/{import_id}/undo", { params: { path: { import_id: item.id } } })), "Import undone");
  const discard = () =>
    act(
      () => unwrap(api.DELETE("/api/v1/imports/{import_id}", { params: { path: { import_id: item.id } } })),
      "Preview discarded",
    );

  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">{item.fileName}</p>
        <p className="text-xs text-ink-faint">
          {[
            item.account.name,
            formatRelative(item.createdAt),
            item.status === "imported" ? `${item.importedCount} of ${item.rowCount} rows imported` : `${item.rowCount} rows`,
          ].join(" · ")}
        </p>
      </div>
      <span className="rounded-full bg-paper px-2 py-0.5 text-xs text-ink-faint">{STATUS_LABELS[item.status]}</span>
      {item.status === "previewing" ? (
        <>
          <Button size="sm" onClick={() => onReview(item.id)}>
            Review
          </Button>
          <Button size="sm" variant="ghost" busy={busy} onClick={discard}>
            Discard
          </Button>
        </>
      ) : null}
      {item.status === "imported" && !asking ? (
        <Button size="sm" onClick={() => setAsking(true)}>
          Undo
        </Button>
      ) : null}
      {item.status === "imported" && asking ? (
        <div className="flex items-center gap-2">
          <span className="text-sm text-ink-soft">Remove {item.importedCount} transactions?</span>
          <Button size="sm" variant="danger" busy={busy} onClick={undo}>
            Yes, undo
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setAsking(false)}>
            Keep
          </Button>
        </div>
      ) : null}
    </li>
  );
}
