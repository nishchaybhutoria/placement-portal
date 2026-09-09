import { useEffect, useState } from "react";

/**
 * The value, held still until it stops changing.
 *
 * Two kinds of control in this app turn a keystroke into a request. A search
 * box feeds its text straight into a screen's query, and `useScreen` keys on
 * that query, so every character is a GET. A `PreviewConfirm` choice feeds the
 * command input, and the dialog dry-runs whenever that input changes, so every
 * character is a POST — against a command that may carry a `rate_limit`, which
 * is how typing a reason could 429 the action it was the reason for.
 *
 * Debouncing the *value* rather than the handler keeps the input itself
 * controlled and instant: the box updates on every keystroke, and only what
 * reads across the wire waits.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [settled, setSettled] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setSettled(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [value, delayMs]);

  return settled;
}

/**
 * How long a search box sits still before its screen is re-queried.
 *
 * Shorter than the command debounce because nothing here is rate limited —
 * screen GETs are not — so this is about request volume and about the list not
 * flashing its skeleton between characters, not about an action becoming
 * impossible to perform.
 */
export const SEARCH_DEBOUNCE_MS = 300;
