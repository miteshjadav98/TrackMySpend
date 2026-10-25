"use client";

import type { MeView } from "@moneymoney/contracts";
import { type FormEvent, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { invalidateLedger, keys, useMe, useQueryClient } from "@/lib/queries";

const CURRENCIES = [
  ["INR", "Indian rupee"],
  ["USD", "US dollar"],
  ["EUR", "Euro"],
  ["GBP", "British pound"],
  ["AED", "UAE dirham"],
  ["SGD", "Singapore dollar"],
  ["AUD", "Australian dollar"],
  ["CAD", "Canadian dollar"],
] as const;

const LOCALES = [
  ["en-IN", "English (India): 1,23,456.00"],
  ["en-US", "English (US): 123,456.00"],
  ["en-GB", "English (UK): 123,456.00"],
] as const;

function timezones(): string[] {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["Asia/Kolkata", "UTC"];
  }
}

export function SettingsScreen() {
  const me = useMe();
  if (!me.data) return null;
  return <SettingsForm me={me.data} />;
}

function SettingsForm({ me }: { me: MeView }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const zones = useMemo(() => timezones(), []);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const updated = await unwrap<MeView>(
        api.PATCH("/api/v1/me/profile", {
          body: {
            displayName: String(form.get("displayName") ?? "").trim() || undefined,
            baseCurrency: String(form.get("baseCurrency")),
            timezone: String(form.get("timezone")),
            locale: String(form.get("locale")),
          },
        }),
      );
      queryClient.setQueryData(keys.me, updated);
      await invalidateLedger(queryClient);
      toast("Settings saved");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, undefined));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto max-w-xl px-4 py-6 md:px-8">
        <h1 className="display text-[1.9rem] leading-tight font-semibold">Settings</h1>
        <p className="mt-1 text-ink-soft">These decide how your messages are read and how amounts are shown.</p>
        <form onSubmit={onSubmit} className="mt-8 flex flex-col gap-5 rounded-[var(--radius-card)] border border-line bg-surface p-5 shadow-[var(--shadow-card)]">
          <Field label="Your name">
            {({ id }) => <Input id={id} name="displayName" defaultValue={me.user.displayName} maxLength={100} required />}
          </Field>
          <Field
            label="Main currency"
            hint="Used when you don't name a currency. Existing entries keep their own currency; nothing is converted."
          >
            {({ id, describedBy }) => (
              <Select id={id} name="baseCurrency" defaultValue={me.profile.baseCurrency} aria-describedby={describedBy}>
                {CURRENCIES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {code}: {name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Time zone" hint="Decides what “today” and “yesterday” mean, and where months begin.">
            {({ id, describedBy }) => (
              <Select id={id} name="timezone" defaultValue={me.profile.timezone} aria-describedby={describedBy}>
                {zones.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone.replace(/_/g, " ")}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Number format">
            {({ id }) => (
              <Select id={id} name="locale" defaultValue={me.profile.locale}>
                {LOCALES.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          {error ? (
            <p role="alert" className="rounded-[10px] bg-danger-wash px-3 py-2 text-sm text-danger">
              {error.message}
            </p>
          ) : null}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" busy={busy}>
              Save changes
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
