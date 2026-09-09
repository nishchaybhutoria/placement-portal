/**
 * Which palette the portal paints in.
 *
 * Both palettes are written and contrast-tested in `index.css`; until now the
 * `dark` class was nailed to `<html>` in the served markup, so the light half
 * was live, tested and unreachable. This module is the only thing that moves
 * that class, and it never names a colour — every component reads tokens, so
 * switching the class is the whole of switching the theme.
 *
 * `system` is the default and is a *standing* choice, not a one-time read: a
 * tab left open across sunset should follow the OS, so `watchSystem` keeps the
 * class in step until the viewer picks a side.
 */
export type Theme = "system" | "light" | "dark";

export const THEMES: readonly Theme[] = ["system", "light", "dark"];

/** Shared with the pre-paint script in `index.html`; changing one changes both. */
export const THEME_STORAGE_KEY = "cds-theme";

const DARK_QUERY = "(prefers-color-scheme: dark)";

function isTheme(value: unknown): value is Theme {
  return value === "system" || value === "light" || value === "dark";
}

/**
 * The stored preference, or `system`.
 *
 * Storage can throw outright rather than merely come back empty — a browser set
 * to block site data, a sandboxed frame — and a theme is not worth a blank
 * page, so every access is guarded.
 */
export function getTheme(): Theme {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

/** Whether `theme` paints dark right now, resolving `system` against the OS. */
export function resolveTheme(theme: Theme): "light" | "dark" {
  if (theme !== "system") return theme;
  try {
    return window.matchMedia(DARK_QUERY).matches ? "dark" : "light";
  } catch {
    return "light";
  }
}

/** Paint `theme`. Tailwind is configured `darkMode: "class"`, so this is it. */
export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", resolveTheme(theme) === "dark");
}

export function setTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // A viewer who cannot persist the choice still gets it for this page.
  }
  applyTheme(theme);
}

/**
 * Follow the OS while the stored choice is `system`; returns an unsubscribe.
 *
 * Reading `getTheme()` inside the listener rather than closing over a value is
 * deliberate: the subscription outlives any single choice, and re-subscribing
 * on every toggle is a leak waiting to happen.
 */
export function watchSystem(): () => void {
  let media: MediaQueryList;
  try {
    media = window.matchMedia(DARK_QUERY);
  } catch {
    return () => {};
  }
  const onChange = () => {
    if (getTheme() === "system") applyTheme("system");
  };
  media.addEventListener("change", onChange);
  return () => media.removeEventListener("change", onChange);
}
