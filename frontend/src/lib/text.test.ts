import { describe, expect, it } from "vitest";

import { counted, humanise, isUuid, lakhs } from "./text";

describe("operator-facing text", () => {
  it("humanises wire values without mangling acronyms", () => {
    expect(humanise("ppo")).toBe("PPO");
    expect(humanise("off_campus")).toBe("Off campus");
    expect(humanise("ctc_annual")).toBe("CTC annual");
    expect(humanise("application_deadline")).toBe("Application deadline");
  });

  it("reads an annual CTC in lakhs without rounding the record", () => {
    // The column is rupees; lakhs is how the figure is quoted. A round number
    // loses the decimals, and one that is not round keeps them.
    expect(lakhs("2400000")).toBe("₹24 LPA");
    expect(lakhs(1853500)).toBe("₹18.54 LPA");
    expect(lakhs("50000")).toBe("₹0.50 LPA");
    // Nothing to show is not "null LPA": the caller renders its own empty state.
    expect(lakhs(null)).toBeNull();
    expect(lakhs(undefined)).toBeNull();
    expect(lakhs("")).toBeNull();
    expect(lakhs("not a number")).toBeNull();
  });

  it("pluralises counted nouns", () => {
    expect(counted(1, "student")).toBe("1 student");
    expect(counted(2, "student")).toBe("2 students");
    expect(counted(2, "person", "people")).toBe("2 people");
  });

  it("recognises UUIDs that should be replaced with human names", () => {
    expect(isUuid("bda9429f-030c-5243-b888-2cad56c0b463")).toBe(true);
    expect(isUuid("21110001")).toBe(false);
  });
});
