import { describe, expect, it } from "vitest";

import {
  formatDate,
  formatDateTime,
  toInstant,
  toLocalDateTimeString,
} from "./date";

describe("date formatting and input conversion", () => {
  it("formats calendar dates correctly", () => {
    expect(formatDate("2026-09-11")).toBe("11 Sept 2026");
    expect(formatDate(null)).toBe("Date unavailable");
    expect(formatDate("")).toBe("Date unavailable");
  });

  it("formats date/time correctly", () => {
    expect(formatDateTime(null)).toBe("Time unavailable");
    expect(formatDateTime("")).toBe("Time unavailable");
  });

  it("converts ISO UTC strings to local YYYY-MM-DDTHH:mm strings for datetime-local inputs", () => {
    // Empty / null cases
    expect(toLocalDateTimeString(null)).toBe("");
    expect(toLocalDateTimeString(undefined)).toBe("");
    expect(toLocalDateTimeString("")).toBe("");
    expect(toLocalDateTimeString("not-a-date")).toBe("");

    // Date object
    const date = new Date(2026, 8, 11, 14, 35); // Month is 0-indexed: 8 is Sept
    expect(toLocalDateTimeString(date)).toBe("2026-09-11T14:35");

    // ISO string round-trip with local time
    const localString = "2026-11-04T10:00";
    const instant = toInstant(localString);
    expect(instant).not.toBeNull();
    // Converting the resulting instant back to local datetime string must restore the original value
    expect(toLocalDateTimeString(instant)).toBe(localString);
  });

  it("converts datetime-local strings to UTC ISO strings", () => {
    expect(toInstant(null)).toBeNull();
    expect(toInstant(undefined)).toBeNull();
    expect(toInstant("")).toBeNull();
    expect(toInstant("invalid")).toBeNull();

    const result = toInstant("2026-11-04T10:00");
    expect(result).toMatch(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$/);
  });
});
