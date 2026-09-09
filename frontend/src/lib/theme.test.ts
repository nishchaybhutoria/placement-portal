import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { applyTheme, getTheme, resolveTheme, setTheme, watchSystem } from "./theme";

/**
 * The theme resolves in three states, and `system` is the one that can be got
 * wrong quietly: it is not a value but a standing deference to the OS, so it
 * has to be re-read rather than snapshotted.
 */
function stubMatchMedia(prefersDark: boolean) {
  const listeners = new Set<() => void>();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: prefersDark,
      addEventListener: (_: string, handler: () => void) => listeners.add(handler),
      removeEventListener: (_: string, handler: () => void) => listeners.delete(handler),
    })),
  );
  return listeners;
}

describe("theme", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.classList.remove("dark");
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("defaults to system and follows the OS preference", () => {
    stubMatchMedia(true);
    expect(getTheme()).toBe("system");
    expect(resolveTheme("system")).toBe("dark");
    applyTheme("system");
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    stubMatchMedia(false);
    applyTheme("system");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });

  it("an explicit choice overrides the OS and persists", () => {
    stubMatchMedia(true);
    setTheme("light");
    expect(getTheme()).toBe("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);

    stubMatchMedia(false);
    setTheme("dark");
    expect(getTheme()).toBe("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);
  });

  it("stops following the OS once a side is chosen", () => {
    const listeners = stubMatchMedia(false);
    const stop = watchSystem();

    setTheme("dark");
    stubMatchMedia(false);
    for (const listener of listeners) listener();
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    stop();
  });

  it("survives storage that refuses to answer", () => {
    stubMatchMedia(false);
    const getItem = vi
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    expect(getTheme()).toBe("system");
    getItem.mockRestore();
  });
});
