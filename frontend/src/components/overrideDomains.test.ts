import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { RULE_DOMAIN_LABELS } from "./EventPayload";

function backendRuleDomains(): string[] {
  const path = resolve(process.cwd(), "../backend/app/domain/shared.py");
  const source = readFileSync(path, "utf8");
  const body = /class RuleDomain\(StrEnum\):\n([\s\S]*?)\n\n/.exec(source)?.[1] ?? "";
  return [...body.matchAll(/^\s+[A-Z][A-Z0-9_]* = "([a-z0-9_]+)"$/gm)].map(
    (match) => match[1]!,
  );
}

describe("override domain display parity", () => {
  const backend = backendRuleDomains();

  it("parses the backend enum non-vacuously", () => {
    expect(backend.length).toBeGreaterThan(5);
  });

  it("has display prose for every backend domain and no retired domains", () => {
    expect(Object.keys(RULE_DOMAIN_LABELS).sort()).toEqual([...backend].sort());
  });
});
