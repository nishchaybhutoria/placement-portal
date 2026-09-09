import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BulkRows, type BulkRow } from "./BulkRows";

/**
 * The shared bulk preview (the design review §4.21, widened by §4.37).
 *
 * What is asserted here is that no row can go missing. Counting an unmatched
 * identifier is how a student silently never gets approved; dropping a row
 * whose status this component has not heard of is the same failure with a
 * different cause.
 */
describe("BulkRows", () => {
  const rows: BulkRow[] = [
    { identifier: "21110001", full_name: "Asha Mehta", roll_number: "21110001", status: "ok" },
    { identifier: "b1", membership_id: "b1", status: "applied" },
    { identifier: "NOT-A-ROLL", status: "error", reason: "unmatched_identifier" },
    { identifier: "21119999", status: "error", reason: "unmatched_identifier" },
    {
      identifier: "21110002",
      full_name: "Rahul Verma",
      status: "skipped",
      reason: "invalid_transition",
      human: "Not sitting in a round",
    },
    { identifier: "21110003", full_name: "Priya Nair", status: "error", reason: "stale_view" },
  ];

  function panel() {
    return render(
      <BulkRows
        summary={{ rows }}
        applyLabel="Will approve"
        resolveName={(row) => (row.membership_id === "b1" ? "Esha Nair" : undefined)}
      />,
    );
  }

  it("names every unmatched identifier instead of counting them", () => {
    panel();
    const section = screen.getByText(/Matched nothing \(2\)/).closest("section")!;
    expect(within(section).getByText("NOT-A-ROLL")).toBeInTheDocument();
    expect(within(section).getByText("21119999")).toBeInTheDocument();
  });

  it("states the planned effect per row and resolves a ticked row's name", () => {
    render(
      <BulkRows
        summary={{ rows }}
        applyLabel="Will approve"
        resolveName={(row) => (row.membership_id === "b1" ? "Esha Nair" : undefined)}
        describe={() => " → active"}
      />,
    );
    const section = screen.getByText(/Will approve \(2\)/).closest("section")!;
    expect(within(section).getByText(/Asha Mehta \(21110001\)/)).toBeInTheDocument();
    // A ticked row comes back as the id it was sent; the screen supplies the name.
    expect(within(section).getByText(/Esha Nair/)).toBeInTheDocument();
    expect(within(section).queryByText(/b1/)).not.toBeInTheDocument();
    expect(within(section).getAllByText("→ active")).toHaveLength(2);
  });

  it("explains a skip with the sentence the server produced", () => {
    panel();
    const section = screen.getByText(/Skipped \(1\)/).closest("section")!;
    expect(within(section).getByText(/Not sitting in a round/)).toBeInTheDocument();
  });

  it("shows a row whose status is neither applied nor skipped", () => {
    panel();
    const section = screen.getByText(/Cannot be done \(1\)/).closest("section")!;
    expect(within(section).getByText(/Priya Nair/)).toBeInTheDocument();
  });

  it("reads an already-correct row as up to date, never as a failure", () => {
    render(
      <BulkRows
        summary={{
          rows: [
            {
              identifier: "21110004",
              full_name: "Kabir Rao",
              status: "unchanged",
            },
          ],
        }}
        applyLabel="Will publish"
      />,
    );
    // Re-uploading a corrected venue sheet is the ordinary case (§4.46): the
    // rows it does not move must not appear under "Cannot be done", and the
    // panel has to say why they are absent from the applying list.
    expect(screen.queryByText(/Cannot be done/)).not.toBeInTheDocument();
    const section = screen.getByText(/Already up to date \(1\)/).closest("section")!;
    expect(within(section).getByText(/Kabir Rao/)).toBeInTheDocument();
    expect(within(section).getByText(/will not be emailed again/)).toBeInTheDocument();
  });

  it("says so plainly when nothing will apply", () => {
    render(
      <BulkRows
        summary={{ rows: [{ identifier: "x", status: "error", reason: "unmatched_identifier" }] }}
        applyLabel="Will approve"
      />,
    );
    expect(screen.getByText("Nobody.")).toBeInTheDocument();
  });
});
