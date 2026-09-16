import { describe, expect, it } from "vitest";

import { batchKeyFor } from "./idempotency";

/**
 * The bound is the whole point: `idempotency_keys.key` carries a unique btree,
 * and PostgreSQL refuses an entry over 2704 bytes. The approvals queue used to
 * build its key out of every ticked id and broke at seventy-two selections.
 */
describe("batchKeyFor", () => {
  const ids = (count: number) =>
    Array.from({ length: count }, (_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, "0")}`);

  it("stays short however large the selection is", () => {
    for (const count of [0, 1, 72, 137, 5000]) {
      expect(batchKeyFor("approvals-cycle", ids(count)).length).toBeLessThan(120);
    }
  });

  it("is the same key for the same selection in any order", () => {
    const selection = ids(137);
    const shuffled = [...selection].reverse();

    expect(batchKeyFor("approvals-c", shuffled)).toBe(batchKeyFor("approvals-c", selection));
  });

  it("is a different key for a different selection", () => {
    const selection = ids(137);

    expect(batchKeyFor("approvals-c", selection.slice(0, 136))).not.toBe(
      batchKeyFor("approvals-c", selection),
    );
    // A row removed and another added leaves the count alone; the key must
    // still move, or the second batch replays the first one's result.
    expect(batchKeyFor("approvals-c", [...selection.slice(1), "extra"])).not.toBe(
      batchKeyFor("approvals-c", selection),
    );
  });

  it("separates an empty selection from a single row", () => {
    expect(batchKeyFor("approvals-c", [])).not.toBe(batchKeyFor("approvals-c", ids(1)));
  });

  it("keeps the prefix, so a key is still recognisable in the audit log", () => {
    expect(batchKeyFor("approvals-c1", ids(3))).toMatch(/^approvals-c1-/);
  });
});
