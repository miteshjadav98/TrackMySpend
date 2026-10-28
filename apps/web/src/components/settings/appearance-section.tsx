"use client";

import { useSyncExternalStore } from "react";

import { SettingsSection } from "@/components/settings/settings-section";
import {
  readThemePreference,
  saveThemePreference,
  subscribeToThemePreference,
  THEME_PREFERENCES,
  type ThemePreference,
} from "@/lib/theme";

const LABELS: Record<ThemePreference, string> = {
  system: "System",
  light: "Light",
  dark: "Dark",
};

/** Settings → Appearance: light, dark, or follow the device. Remembered in this browser. */
export function AppearanceSection() {
  // Read from storage (not component state), so it stays right while the page is kept alive.
  // The server can't see localStorage, so it renders "system" and the browser corrects it.
  const current = useSyncExternalStore(subscribeToThemePreference, readThemePreference, () => "system" as const);

  return (
    <SettingsSection title="Appearance" description="Light, dark, or match this device. Saved in this browser.">
      <div role="radiogroup" aria-label="Theme" className="grid grid-cols-3 gap-1 rounded-xl bg-paper p-1">
        {THEME_PREFERENCES.map((preference) => {
          const selected = preference === current;
          return (
            <button
              key={preference}
              type="button"
              role="radio"
              aria-checked={selected}
              onClick={() => saveThemePreference(preference)}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                selected ? "bg-surface text-ink shadow-sm ring-1 ring-line" : "text-ink-soft hover:text-ink"
              }`}
            >
              {LABELS[preference]}
            </button>
          );
        })}
      </div>
    </SettingsSection>
  );
}
