"use client";

import type { ColumnMap, ImportDetail, RowChange, RowStatus } from "@moneymoney/contracts";
import { type FormEvent, useState } from "react";

import { LayoutStep } from "@/components/imports/layout-step";
import { PreviewStep } from "@/components/imports/preview-step";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { accountOptionLabel } from "@/lib/format";
import { invalidateLedger, keys, useAccounts, useCategories, useImport, useQueryClient } from "@/lib/queries";

const PAGE = 200;

function messageOf(caught: unknown): string {
  return caught instanceof ApiError ? caught.message : new ApiError(0, undefined).message;
}

/**
 * Import a statement in one dialog: pick the account and file, confirm the columns (first time
 * only), review the preview, then import. The parent mounts it fresh each time it opens, so
 * nothing from an earlier import is left in its state.
 */
export function ImportStatementDialog({
  onClose,
  initialImportId = null,
}: {
  onClose: () => void;
  /** Reopen a preview that was left unsaved. */
  initialImportId?: string | null;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const accounts = useAccounts();
  const categories = useCategories();

  const [importId, setImportId] = useState<string | null>(initialImportId);
  const [accountId, setAccountId] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [statusFilter, setStatusFilter] = useState<RowStatus | "">("");
  const [limit, setLimit] = useState(PAGE);
  const [changingColumns, setChangingColumns] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const preview = useImport(importId, statusFilter, limit);
  const detail = preview.data;

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  // Every query of this import (any filter or page size) shares the ["imports", id] prefix.
  const refresh = () => queryClient.invalidateQueries({ queryKey: [...keys.imports, importId] });

  function upload(event: FormEvent) {
    event.preventDefault();
    if (!file || !accountId) return;
    void run(async () => {
      const started = await unwrap<ImportDetail>(
        api.POST("/api/v1/imports", {
          body: { accountId, file: "" },
          // The file travels as multipart form data, not JSON.
          bodySerializer: () => {
            const form = new FormData();
            form.append("accountId", accountId);
            form.append("file", file);
            return form;
          },
        }),
      );
      setImportId(started.id);
      setChangingColumns(false);
      await queryClient.invalidateQueries({ queryKey: keys.imports });
    });
  }

  function saveLayout(layout: ColumnMap) {
    if (!importId) return;
    void run(async () => {
      await unwrap<ImportDetail>(
        api.PUT("/api/v1/imports/{import_id}/layout", { params: { path: { import_id: importId } }, body: layout }),
      );
      setChangingColumns(false);
      await refresh();
    });
  }

  function changeRows(rows: RowChange[]) {
    if (!importId) return;
    void run(async () => {
      await unwrap<ImportDetail>(
        api.PATCH("/api/v1/imports/{import_id}/rows", { params: { path: { import_id: importId } }, body: { rows } }),
      );
      await refresh();
    });
  }

  function confirm() {
    if (!importId) return;
    void run(async () => {
      const done = await unwrap<ImportDetail>(
        api.POST("/api/v1/imports/{import_id}/confirm", { params: { path: { import_id: importId } } }),
      );
      await invalidateLedger(queryClient);
      toast(`Imported ${done.importedCount} transactions from ${done.fileName}`);
    });
  }

  function undo() {
    if (!importId) return;
    void run(async () => {
      await unwrap<ImportDetail>(api.POST("/api/v1/imports/{import_id}/undo", { params: { path: { import_id: importId } } }));
      await invalidateLedger(queryClient);
      toast("Import undone. Its transactions are removed.");
      onClose();
    });
  }

  function body() {
    if (importId === null) {
      return (
        <UploadForm
          accounts={accounts.data ?? []}
          accountId={accountId}
          onAccount={setAccountId}
          onFile={setFile}
          canSubmit={Boolean(file && accountId)}
          busy={busy}
          error={error}
          onSubmit={upload}
        />
      );
    }
    if (preview.isPending) return <p className="py-8 text-center text-sm text-ink-faint">Reading your statement…</p>;
    if (preview.isError || !detail) {
      return (
        <p role="alert" className="py-8 text-center text-sm text-danger">
          {preview.isError ? messageOf(preview.error) : "Could not load this import."}
        </p>
      );
    }
    if (detail.status === "imported") {
      return <DoneStep detail={detail} busy={busy} error={error} onUndo={undo} onClose={onClose} />;
    }
    if (detail.status === "undone") {
      return <p className="py-8 text-center text-sm text-ink-soft">This import was undone.</p>;
    }
    if (!detail.layoutConfirmed || changingColumns) {
      return <LayoutStep detail={detail} busy={busy} error={error} onConfirm={saveLayout} />;
    }
    return (
      <PreviewStep
        detail={detail}
        categories={categories.data ?? []}
        statusFilter={statusFilter}
        onStatusFilter={(status) => {
          setStatusFilter(status);
          setLimit(PAGE);
        }}
        onChangeRows={changeRows}
        onShowMore={() => setLimit((current) => current + PAGE)}
        onChangeColumns={() => setChangingColumns(true)}
        onConfirm={confirm}
        busy={busy}
        error={error}
      />
    );
  }

  return (
    <Dialog
      open
      wide
      onClose={onClose}
      title="Import statement"
      description={detail ? `${detail.fileName} · ${detail.account.name}` : undefined}
    >
      {body()}
    </Dialog>
  );
}

function UploadForm({
  accounts,
  accountId,
  onAccount,
  onFile,
  canSubmit,
  busy,
  error,
  onSubmit,
}: {
  accounts: { id: string; name: string; isArchived: boolean }[];
  accountId: string;
  onAccount: (id: string) => void;
  onFile: (file: File | null) => void;
  canSubmit: boolean;
  busy: boolean;
  error: string | null;
  onSubmit: (event: FormEvent) => void;
}) {
  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <p className="text-sm text-ink-soft">
        Upload the CSV your bank or card gives you. Nothing is saved until you review the preview.
      </p>
      <Field label="Account" hint="Every row will be filed under this account.">
        {({ id, describedBy }) => (
          <Select id={id} aria-describedby={describedBy} required value={accountId} onChange={(event) => onAccount(event.target.value)}>
            <option value="">Choose an account</option>
            {accounts.map((account) => (
              <option key={account.id} value={account.id}>
                {accountOptionLabel(account)}
              </option>
            ))}
          </Select>
        )}
      </Field>
      <Field label="Statement file (CSV)" hint="Up to 5 MB and 5,000 rows.">
        {({ id, describedBy }) => (
          <Input
            id={id}
            aria-describedby={describedBy}
            type="file"
            accept=".csv,text/csv"
            required
            className="py-1.5"
            onChange={(event) => onFile(event.target.files?.[0] ?? null)}
          />
        )}
      </Field>
      {accounts.length === 0 ? <p className="text-sm text-ink-soft">Add an account in Settings first, then come back.</p> : null}
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex justify-end">
        <Button type="submit" variant="primary" busy={busy} disabled={!canSubmit}>
          Read statement
        </Button>
      </div>
    </form>
  );
}

function DoneStep({
  detail,
  busy,
  error,
  onUndo,
  onClose,
}: {
  detail: ImportDetail;
  busy: boolean;
  error: string | null;
  onUndo: () => void;
  onClose: () => void;
}) {
  return (
    <div className="flex flex-col items-center gap-4 py-6 text-center">
      <p className="display text-lg font-semibold">
        {detail.importedCount} {detail.importedCount === 1 ? "transaction" : "transactions"} imported
      </p>
      <p className="text-sm text-ink-soft">
        {detail.skippedCount} {detail.skippedCount === 1 ? "row was" : "rows were"} left out. You can undo this import
        from the Imports list at any time.
      </p>
      {error ? (
        <p role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
      <div className="flex gap-2">
        <Button busy={busy} onClick={onUndo}>
          Undo import
        </Button>
        <Button variant="primary" onClick={onClose}>
          Done
        </Button>
      </div>
    </div>
  );
}
