import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useDebouncedValue } from "./useDebouncedValue";

describe("useDebouncedValue", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("returns the first value without waiting", () => {
    const { result } = renderHook(() => useDebouncedValue("a", 300));

    expect(result.current).toBe("a");
  });

  it("holds the value until the delay elapses", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 300),
      { initialProps: { value: "a" } },
    );

    rerender({ value: "ab" });
    expect(result.current).toBe("a");

    act(() => void vi.advanceTimersByTime(299));
    expect(result.current).toBe("a");

    act(() => void vi.advanceTimersByTime(1));
    expect(result.current).toBe("ab");
  });

  it("emits once for a burst, not once per change", () => {
    const { result, rerender } = renderHook(
      ({ value }) => useDebouncedValue(value, 300),
      { initialProps: { value: "" } },
    );

    for (const value of ["L", "La", "Lat", "Late"]) {
      rerender({ value });
      act(() => void vi.advanceTimersByTime(50));
    }
    expect(result.current).toBe("");

    act(() => void vi.advanceTimersByTime(300));
    expect(result.current).toBe("Late");
  });
});
