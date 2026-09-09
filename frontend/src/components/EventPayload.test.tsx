import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { EventPayload } from "./EventPayload";

/**
 * The event payload, rendered (the design review §4.35).
 *
 * The load-bearing case is the override: INT-2 stamps `applied_override_ids`
 * into the event of every decision an override influenced, and a dispute about
 * whether an application was ordinary is answered from that stamp or from the
 * database. So the row states the domain, the granter, the date and — inline,
 * not behind a disclosure — the reason. The rest of these prove the second
 * half of the rule: known keys read as sentences, and a key this component has
 * never heard of still reaches the reader.
 */
describe("EventPayload", () => {
  const override = {
    id: "5b0a1e2c-0000-4000-8000-000000000001",
    rule_domain: "eligibility",
    allow: true,
    reason: "Company asked for him by name after the robotics showcase",
    granted_by: "CDS Administrator",
    granted_at: "2026-01-04T10:30:00+00:00",
  };

  it("reads an applied override as prose, with its reason inline", () => {
    render(
      <EventPayload
        payload={{
          job_id: "0f3f1a55-0000-4000-8000-00000000000a",
          applied_override_ids: [override.id],
        }}
        labels={{ applied_override_ids: [override] }}
      />,
    );
    const row = screen.getByText(/Eligibility requirement waived/);
    expect(row).toHaveTextContent("override granted by CDS Administrator");
    expect(row).toHaveTextContent(
      "reason: Company asked for him by name after the robotics showcase",
    );
    // The id is never what the reader is shown.
    expect(screen.queryByText(new RegExp(override.id))).not.toBeInTheDocument();
  });

  it("reads a closing override the other way round", () => {
    render(
      <EventPayload
        payload={{ applied_override_ids: [override.id] }}
        labels={{
          applied_override_ids: [
            { ...override, allow: false, rule_domain: "offer_cap", reason: "Under review" },
          ],
        }}
      />,
    );
    expect(screen.getByText(/Offer cap closed/)).toBeInTheDocument();
  });

  it("says a grant is gone rather than printing the id it could not resolve", () => {
    render(
      <EventPayload
        payload={{ applied_override_ids: [override.id] }}
        labels={{
          applied_override_ids: [
            {
              id: override.id,
              rule_domain: null,
              allow: null,
              reason: null,
              granted_by: null,
              granted_at: null,
            },
          ],
        }}
      />,
    );
    expect(
      screen.getByText("An override influenced this decision, and the grant is no longer available."),
    ).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(override.id))).not.toBeInTheDocument();
  });

  it("states a cascade's cause and who performed it", () => {
    render(
      <EventPayload
        payload={{
          trigger: "acceptance",
          system_initiated: true,
          acceptance_offer_id: "0f3f1a55-0000-4000-8000-00000000000b",
        }}
      />,
    );
    expect(screen.getByText("Caused by acceptance")).toBeInTheDocument();
    expect(screen.getByText("Applied by the system, not by a person")).toBeInTheDocument();
  });

  it("states an attendance change as one sentence, not two halves", () => {
    render(
      <EventPayload payload={{ attendance: "absent", previous: "unknown", strike_awarded: true }} />,
    );
    expect(screen.getByText("Attendance: unknown → absent")).toBeInTheDocument();
    expect(screen.getByText("A strike was awarded")).toBeInTheDocument();
    expect(screen.queryByText(/Previously/)).not.toBeInTheDocument();
  });

  it("keeps a key it has never heard of, in the disclosure", () => {
    render(<EventPayload payload={{ termination_kind: "cascade", some_future_key: 41 }} />);
    expect(screen.getByText("Termination: cascade")).toBeInTheDocument();
    expect(screen.getByText("Payload (1)")).toBeInTheDocument();
    expect(screen.getByText("Some future key")).toBeInTheDocument();
    expect(screen.getByText("41")).toBeInTheDocument();
  });

  it("renders nothing when the payload holds nothing worth saying", () => {
    const { container } = render(<EventPayload payload={{ applied_override_ids: [] }} />);
    expect(container).toBeEmptyDOMElement();
  });
});
