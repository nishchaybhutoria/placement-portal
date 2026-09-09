import { describe, expect, it } from "vitest";

import { counted, humanise } from "./text";

describe("operator-facing text", () => {
  it("humanises wire values without mangling acronyms", () => {
    expect(humanise("ppo")).toBe("PPO");
    expect(humanise("off_campus")).toBe("Off campus");
    expect(humanise("ctc_lpa")).toBe("CTC LPA");
    expect(humanise("application_deadline")).toBe("Application deadline");
  });

  it("pluralises counted nouns", () => {
    expect(counted(1, "student")).toBe("1 student");
    expect(counted(2, "student")).toBe("2 students");
    expect(counted(2, "person", "people")).toBe("2 people");
  });
});
