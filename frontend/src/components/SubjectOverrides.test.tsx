import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SubjectOverrides } from "./SubjectOverrides";

describe("SubjectOverrides", () => {
  it("shows active, expired, and resolver-shadowed grants with their reasons", () => {
    render(
      <SubjectOverrides
        overrides={[
          {
            id: "1",
            rule_domain: "offer_cap",
            allow: true,
            scope: "application",
            state: "active",
            reason: "Committee approval",
            expires_at: null,
            subject_label: null,
          },
          {
            id: "2",
            rule_domain: "offer_cap",
            allow: false,
            scope: "job",
            state: "shadowed",
            reason: "Temporary freeze",
            expires_at: null,
            subject_label: "Placement — Northwind — SRE",
          },
          {
            id: "3",
            rule_domain: "offer_deadline",
            allow: true,
            scope: "enrollment",
            state: "expired",
            reason: "Medical extension",
            expires_at: "2027-01-02T00:00:00Z",
            subject_label: null,
          },
        ]}
      />,
    );

    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("Shadowed")).toBeInTheDocument();
    expect(screen.getByText("Expired")).toBeInTheDocument();
    expect(screen.getByText("Committee approval")).toBeInTheDocument();
    expect(screen.getByText("Temporary freeze")).toBeInTheDocument();
    expect(
      screen.getByText("A more specific, blocking, or newer override currently wins."),
    ).toBeInTheDocument();
  });
});
