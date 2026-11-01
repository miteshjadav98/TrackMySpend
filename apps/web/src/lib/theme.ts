/**
 * Light and dark mode.
 *
 * The user picks "system", "light" or "dark" (Settings → Appearance); the choice is kept in
 * this browser's localStorage. The page shows the theme through `data-theme` on <html>, which
 * globals.css reads. "system" follows the operating system, including when it changes.
 */

export type ThemePreference = "system" | "light" | "dark";

export const THEME_PREFERENCES: readonly ThemePreference[] = ["system", "light", "dark"];

const STORAGE_KEY = "mm-theme";
const DARK_QUERY = "(prefers-color-scheme: dark)";

export function readThemePreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    return "system"; // storage blocked (private mode, strict settings)
  }
}

// Components that show the current choice (Settings → Appearance) re-render when it changes.
const preferenceListeners = new Set<() => void>();

export function subscribeToThemePreference(onChange: () => void): () => void {
  preferenceListeners.add(onChange);
  return () => preferenceListeners.delete(onChange);
}

export function saveThemePreference(preference: ThemePreference): void {
  try {
    localStorage.setItem(STORAGE_KEY, preference);
  } catch {
    // Storage blocked: the choice still applies to this page, it just isn't remembered.
  }
  applyTheme(preference);
  preferenceListeners.forEach((notify) => notify());
}

/** Show the theme a preference means right now. */
export function applyTheme(preference: ThemePreference): void {
  const dark = preference === "dark" || (preference === "system" && matchMedia(DARK_QUERY).matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}

/** While the preference is "system", follow the OS when it switches. Returns a stop function. */
export function followSystemTheme(): () => void {
  const media = matchMedia(DARK_QUERY);
  const onChange = () => {
    if (readThemePreference() === "system") applyTheme("system");
  };
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}

/**
 * Runs inline in <head> before the page paints, so a dark-mode user never sees a white flash.
 * It repeats `applyTheme(readThemePreference())` in plain JavaScript because nothing else has
 * loaded yet at that point.
 */
export const THEME_BOOT_SCRIPT = `(function(){try{var p=localStorage.getItem("${STORAGE_KEY}");var d=p==="dark"||(p!=="light"&&matchMedia("${DARK_QUERY}").matches);document.documentElement.dataset.theme=d?"dark":"light"}catch(e){document.documentElement.dataset.theme="light"}})();`;
