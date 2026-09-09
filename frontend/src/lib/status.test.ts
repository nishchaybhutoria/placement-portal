import { describe, expect, it } from "vitest";

import {
  APPLICATION_STATUS,
  ATTENDANCE_STATUS,
  EXTERNAL_STATUS,
  MEMBERSHIP_STATUS,
  ROUND_RESULT,
  SEMANTIC_FAMILIES,
  statusMeta,
} from "./status";

/** Guards the DESIGN.md §4 mapping against silent drift. */
describe("status chip mapping", () => {
  it("is exhaustive over the LLD §6 enums", () => {
    expect(Object.keys(APPLICATION_STATUS).sort()).toEqual(
      [
        "accepted",
        "auto_withdrawn",
        "declined",
        "in_progress",
        "offer_terminated",
        "offered",
        "pending_offer",
        "rejected",
        "withdrawn",
      ].sort(),
    );
    expect(Object.keys(ATTENDANCE_STATUS).sort()).toEqual(
      ["absent", "excused", "pending", "present"].sort(),
    );
    expect(Object.keys(MEMBERSHIP_STATUS).sort()).toEqual(
      ["active", "pending", "rejected", "removed", "withdrawn"].sort(),
    );
    expect(Object.keys(ROUND_RESULT).sort()).toEqual(
      ["advanced", "eliminated", "pending", "waitlisted"].sort(),
    );
    expect(Object.keys(EXTERNAL_STATUS).sort()).toEqual(
      ["accepted", "declined", "offered"].sort(),
    );
  });

  it("uses only declared semantic families", () => {
    for (const table of [
      APPLICATION_STATUS,
      ATTENDANCE_STATUS,
      MEMBERSHIP_STATUS,
      ROUND_RESULT,
      EXTERNAL_STATUS,
    ]) {
      for (const meta of Object.values(table)) {
        expect(SEMANTIC_FAMILIES).toContain(meta.family);
      }
    }
  });

  it("reserves danger for outcomes imposed on the student", () => {
    // The load-bearing rule in DESIGN.md §4.1. Freely-made choices are neutral.
    expect(APPLICATION_STATUS.declined.family).toBe("neutral");
    expect(APPLICATION_STATUS.withdrawn.family).toBe("neutral");
    expect(MEMBERSHIP_STATUS.withdrawn.family).toBe("neutral");
    expect(APPLICATION_STATUS.rejected.family).toBe("danger");
    expect(APPLICATION_STATUS.offer_terminated.family).toBe("danger");
    expect(MEMBERSHIP_STATUS.removed.family).toBe("danger");
    expect(ROUND_RESULT.eliminated.family).toBe("danger");
    expect(EXTERNAL_STATUS.declined.family).toBe("neutral");
  });

  it("keeps offered distinct from accepted", () => {
    expect(APPLICATION_STATUS.offered.family).not.toBe(APPLICATION_STATUS.accepted.family);
  });

  it("humanises an unmapped value instead of leaking the raw token", () => {
    expect(statusMeta("application", "some_new_state")).toEqual({
      label: "Some new state",
      family: "neutral",
    });
  });
});
