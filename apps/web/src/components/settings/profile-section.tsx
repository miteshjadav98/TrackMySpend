"use client";

import type { MeView } from "@moneymoney/contracts";
import { type FormEvent, useMemo, useState } from "react";

import { SettingsSection } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/field";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, unwrap } from "@/lib/api";
import { CURRENCIES } from "@/lib/format";
import { invalidateLedger, keys, useMe, useQueryClient } from "@/lib/queries";

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

/** Settings → Profile: your name, main currency, time zone and number format. */
export function ProfileSection() {
  const me = useMe();
  // The form fills its fields from `me` once, when it mounts, so it waits for the data.
  if (!me.data) return null;
  return (
    <SettingsSection title="Profile" description="These decide how your messages are read and how amounts are shown.">
      <ProfileForm me={me.data} />
    </SettingsSection>
  );
}

function ProfileForm({ me }: { me: MeView }) {
  const queryClient = useQueryClient();
  const toast = useToast();
  // Browsers list some zones under older names (Chrome and Edge say "Asia/Calcutta", not
  // "Asia/Kolkata"). Without the saved zone in the list, the picker would show the first zone
  // and "Save" would silently move the user to it.
  const zones = useMemo(() => {
    const all = timezones();
    return all.includes(me.profile.timezone) ? all : [me.profile.timezone, ...all];
  }, [me.profile.timezone]);
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
    <form onSubmit={onSubmit} className="flex flex-col gap-5">
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
  );
}
