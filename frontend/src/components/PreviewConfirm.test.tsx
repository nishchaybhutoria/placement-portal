import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderScreen } from "@/test/harness";
import { PreviewConfirm } from "./PreviewConfirm";

/**
 * The dry runs a dialog fires while its operator is still typing.
 *
 * the design review §4.39 removed dry runs from the route limiter's write budget, and
 * required the other half: a preview the operator has already superseded is
 * cancelled rather than left to race the one that replaced it. `dismiss_finding`
 * is the exact shape the ruling was written about — a required free-text reason,
 * on a command carrying `rate_limit="10/min"`.
 */
describe("PreviewConfirm", () => {
  afterEach(() => vi.unstubAllGlobals());

  /** Every preview stays pending until its own signal aborts it. */
  function mockPendingPreviews() {
    const signals: AbortSignal[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
        const signal = init?.signal;
        if (signal) signals.push(signal);
        return new Promise<Response>((resolve, reject) => {
          signal?.addEventListener("abort", () =>
            reject(new DOMException("Aborted", "AbortError")),
          );
          if (!signal) {
            resolve(
              new Response(JSON.stringify({ summary: {}, events: [] }), {
                status: 200,
                headers: { "Content-Type": "application/json" },
              }),
            );
          }
        });
      }),
    );
    return signals;
  }

  function open() {
    const signals = mockPendingPreviews();
    renderScreen(
      <PreviewConfirm
        command="dismiss_finding"
        input={{ finding_id: "8f1d0f2e-6b3a-4c1e-9d7a-2f5b0c4e1a33", reason: "" }}
        title="Dismiss this finding?"
        confirmLabel="Dismiss"
        choices={[{ name: "reason", label: "Reason", kind: "textarea", required: true }]}
        trigger={<button type="button">Dismiss</button>}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    return signals;
  }

  it("cancels a dry run the operator has already superseded", async () => {
    const signals = open();

    // A required choice holds the first dry run until it is answered, which is
    // what makes the reason itself the trigger for every preview that follows.
    const reason = await screen.findByRole("textbox", { name: /^Reason/ });
    fireEvent.change(reason, { target: { value: "Cleared with the registrar" } });
    await waitFor(() => expect(signals).toHaveLength(1));

    fireEvent.change(reason, { target: { value: "Cleared with the registrar on 5 Sep" } });
    await waitFor(() => expect(signals).toHaveLength(2));

    // The superseded run is dead on the wire; only the one describing what
    // Confirm would now send is still outstanding.
    expect(signals[0]!.aborted).toBe(true);
    expect(signals[1]!.aborted).toBe(false);
  });

  it("carries a signal on every dry run it fires", async () => {
    const signals = open();

    const reason = await screen.findByRole("textbox", { name: /^Reason/ });
    fireEvent.change(reason, { target: { value: "Duplicate of an earlier finding" } });
    await waitFor(() => expect(signals).toHaveLength(1));

    // A dry run with no signal cannot be cancelled at all, which is the defect
    // this pair exists to keep out rather than a detail of this dialog.
    expect(signals.every((signal) => signal instanceof AbortSignal)).toBe(true);
  });
});
