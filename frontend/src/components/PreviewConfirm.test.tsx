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

  it("waits for a select whose seeded value is not one it offers", async () => {
    // The join dialog's shape: the command carries `consent: false`, and the
    // consent select offers only "true". "false" is a non-empty string, so the
    // dialog used to read the question as answered, fire the dry run, and open
    // onto the server refusing the join for want of the consent nobody had
    // been given the chance to give.
    const signals = mockPendingPreviews();
    renderScreen(
      <PreviewConfirm
        command="join_cycle"
        input={{
          cycle_id: "2a0d1c9e-8b7f-4a62-9c3d-5e6f70a1b2c3",
          enrollment_id: "7d5e4c3b-2a19-4f8e-b6d5-4c3b2a190f8e",
          default_resume_id: "9f8e7d6c-5b4a-4392-8170-6f5e4d3c2b1a",
          consent: false,
        }}
        title="Join this cycle?"
        confirmLabel="Join"
        choices={[
          {
            name: "consent",
            label: "Consent",
            kind: "select",
            required: true,
            coerce: "boolean",
            options: [{ value: "true", label: "I consent to sharing my application data" }],
          },
        ]}
        trigger={<button type="button">Join</button>}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Join" }));
    const consent = await screen.findByRole("combobox", { name: /^Consent/ });

    // Long enough that the debounce is not what is holding the dry run back.
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(signals).toHaveLength(0);
    expect(screen.queryByText(/was rejected/i)).toBeNull();

    fireEvent.change(consent, { target: { value: "true" } });
    await waitFor(() => expect(signals).toHaveLength(1));
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
