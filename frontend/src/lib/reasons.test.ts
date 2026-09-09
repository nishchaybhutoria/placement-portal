import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { REASON_CODES, reasonText } from "./reasons";

/**
 * the build contract F1 gate: "reasons.ts mirroring backend codes (CI check: sets equal)".
 *
 * Parses the Python module rather than a checked-in snapshot, so adding a code
 * to the backend without adding it here fails immediately.
 */
function backendReasonCodes(): string[] {
  // Vitest runs with `frontend/` as cwd; jsdom does not give `import.meta.url`
  // a file: scheme, so resolve from there instead.
  const path = resolve(process.cwd(), "../backend/app/core/errors.py");
  const source = readFileSync(path, "utf8");
  const codes: string[] = [];
  for (const line of source.split("\n")) {
    const match = /^[A-Z][A-Z0-9_]* = "([a-z0-9_]+)"$/.exec(line);
    if (match?.[1]) codes.push(match[1]);
  }
  return codes;
}

describe("reasons.ts / errors.py parity", () => {
  const backend = backendReasonCodes();

  it("finds the backend constants at all", () => {
    // Guards against the parse silently returning [] if errors.py is restyled,
    // which would make the equality assertion below pass vacuously.
    expect(backend.length).toBeGreaterThan(50);
  });

  it("has exactly the backend's code set", () => {
    expect([...REASON_CODES].sort()).toEqual([...backend].sort());
  });

  it("has no duplicate codes on either side", () => {
    expect(new Set(backend).size).toBe(backend.length);
    expect(new Set(REASON_CODES).size).toBe(REASON_CODES.length);
  });
});

describe("reasonText", () => {
  it("prefers the server's human string", () => {
    expect(reasonText("not_eligible", "Server says no")).toBe("Server says no");
  });

  it("falls back to the local table", () => {
    expect(reasonText("not_eligible")).toMatch(/eligibility/i);
  });

  it("never renders empty for an unknown code", () => {
    expect(reasonText("some_future_code")).toBe("some_future_code");
  });
});
