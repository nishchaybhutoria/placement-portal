import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ExternalOfferPlan,
  MembershipExitPlan,
  OfferActionPlan,
  ReinstatementPlan,
  TerminationPlan,
} from "./CommandSummaryDetails";

describe("consequential command summary arrays", () => {
  it("renders reinstatement round states by round, result, and attendance", () => {
    render(
      <ReinstatementPlan
        summary={{
          cleared_round_states: [
            { round_id: "round-2", round_name: "Technical", result: "waitlisted", attendance: "absent" },
          ],
          kept_round_states: [
            { round_id: "round-1", round_name: "Screening", result: "passed", attendance: "present" },
          ],
        }}
      />,
    );

    const cleared = screen.getByText("Round states cleared", { exact: true }).closest("section")!;
    expect(within(cleared).getByRole("listitem"))
      .toHaveTextContent(/Technical.*result: waitlisted.*attendance: absent/);
    const kept = screen.getByText("Round states kept", { exact: true }).closest("section")!;
    expect(within(kept).getByRole("listitem"))
      .toHaveTextContent(/Screening.*result: passed.*attendance: present/);
  });

  it("names membership applications on both sides of the exit boundary", () => {
    render(
      <MembershipExitPlan
        summary={{
          auto_withdrawn: [
            { application_id: "app-1", job: "Backend Engineer", from_status: "in_progress" },
          ],
          untouched: [
            { application_id: "app-2", job: "Platform Engineer", status: "accepted", suggested_command: "terminate_offer" },
          ],
        }}
      />,
    );

    const auto = screen.getByText("Will auto-withdraw", { exact: true }).closest("section")!;
    expect(within(auto).getByRole("listitem"))
      .toHaveTextContent(/Backend Engineer.*from in progress/);
    const untouched = screen.getByText("Will remain untouched", { exact: true }).closest("section")!;
    expect(within(untouched).getByRole("listitem"))
      .toHaveTextContent(/Platform Engineer.*accepted.*use terminate offer/);
  });

  it("names every application changed by offer acceptance", () => {
    render(
      <OfferActionPlan
        summary={{
          status: "accepted",
          cascade: [
            {
              application_id: "app-1",
              job: "Data Engineer",
              company: "Northwind",
              cycle: "Placement 2026",
              from_status: "offered",
              to_status: "declined",
            },
          ],
          applied_override_ids: [],
        }}
      />,
    );

    const affected = screen.getByText("Other applications affected", { exact: true }).closest("section")!;
    expect(within(affected).getByRole("listitem"))
      .toHaveTextContent(/Data Engineer.*Northwind.*Placement 2026.*offered.*declined/);
  });

  it("renders external-offer effects, cascade, candidates, and selected restorations", () => {
    render(
      <ExternalOfferPlan
        summary={{
          automatic_effects: [{ effect: "placed_dimensions_rederived" }],
          cascade: [
            { application_id: "app-1", job: "Analyst", from_status: "in_progress", to_status: "auto_withdrawn" },
          ],
          restoration_candidates: [
            {
              application_id: "app-2",
              job: "Developer",
              current_status: "auto_withdrawn",
              restore_status: "in_progress",
              target_round_id: "round-1",
              selected: true,
              can_restore: true,
            },
          ],
          restored: [
            { application_id: "app-2", status: "in_progress", target_round_id: "round-1", fresh_offer_id: null },
          ],
        }}
      />,
    );

    expect(screen.getByText("placed dimensions rederived")).toBeInTheDocument();
    const affected = screen.getByText("Other applications affected", { exact: true }).closest("section")!;
    expect(within(affected).getByRole("listitem"))
      .toHaveTextContent(/Analyst.*in progress.*auto withdrawn/);
    const decisions = screen.getByText("Restoration decisions", { exact: true }).closest("section")!;
    expect(within(decisions).getByRole("listitem"))
      .toHaveTextContent(/Restore Developer.*auto withdrawn.*in progress/);
    const restored = screen.getByText("Will restore", { exact: true }).closest("section")!;
    expect(within(restored).getByRole("listitem"))
      .toHaveTextContent(/Developer.*prior round restored/);
  });

  it("keeps each terminate-offer restoration candidate in the command preview", () => {
    render(
      <TerminationPlan
        summary={{
          automatic_effects: [{ effect: "offer_terminated" }],
          restoration_candidates: [
            {
              application_id: "app-1",
              job: "Backend Engineer",
              current_status: "auto_withdrawn",
              restore_status: "in_progress",
              target_round_id: null,
              selected: false,
              can_restore: true,
            },
            {
              application_id: "app-2",
              job: "Frontend Engineer",
              current_status: "declined",
              restore_status: "offered",
              target_round_id: "round-2",
              selected: true,
              requires_fresh_offer: true,
              can_restore: true,
            },
          ],
          restored: [
            { application_id: "app-2", status: "offered", target_round_id: "round-2", fresh_offer_id: "offer-2" },
          ],
        }}
      />,
    );

    const decisions = screen.getByText("Restoration decisions", { exact: true }).closest("section")!;
    const decisionRows = within(decisions).getAllByRole("listitem");
    expect(decisionRows[0]).toHaveTextContent(/Leave Backend Engineer/);
    expect(decisionRows[1]).toHaveTextContent(/Restore Frontend Engineer.*fresh offer/);
    const restored = screen.getByText("Will restore", { exact: true }).closest("section")!;
    expect(within(restored).getByRole("listitem"))
      .toHaveTextContent(/Frontend Engineer.*Offered.*prior round restored.*fresh offer/);
  });
});
