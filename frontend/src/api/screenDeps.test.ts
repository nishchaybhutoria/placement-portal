import { describe, expect, it } from "vitest";

import { SCREEN_DEPS, screenDeps } from "./screenDeps";

/**
 * The map is typed, so a missing or misspelled key is already a compile error.
 * These tests cover what the type system cannot: that the values are sane.
 */
describe("SCREEN_DEPS", () => {
  it("covers every command", () => {
    expect(Object.keys(SCREEN_DEPS).length).toBeGreaterThan(30);
  });

  it("lists no screen twice for one command", () => {
    for (const [name, screens] of Object.entries(SCREEN_DEPS)) {
      expect(new Set(screens).size, `${name} repeats a screen`).toBe(screens.length);
    }
  });

  it("invalidates the approvals board when a membership decision lands", () => {
    expect(screenDeps("approve_memberships")).toContain("staff/cycle/{id}/approvals");
    expect(screenDeps("reject_membership")).toContain("staff/cycle/{id}/approvals");
  });

  it("drops the joinable list when a cycle stops being joinable", () => {
    expect(screenDeps("archive_cycle")).toContain("cycles/joinable");
    expect(screenDeps("set_cycle_active")).toContain("cycles/joinable");
  });
});
