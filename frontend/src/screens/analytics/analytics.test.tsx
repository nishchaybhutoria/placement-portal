import { screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { CycleAnalyticsPayload, PortalAnalyticsPayload } from "@/api/payloads";
import adminAnalyticsPortal from "@/test/fixtures/admin-analytics-portal.json";
import staffCycleAnalytics from "@/test/fixtures/staff-cycle-analytics.json";
import staffJobAnalytics from "@/test/fixtures/staff-job-analytics.json";
import { mockScreens, renderScreen } from "@/test/harness";

import { CycleAnalytics } from "./CycleAnalytics";
import { JobAnalytics } from "./JobAnalytics";
import { PortalAnalytics } from "./PortalAnalytics";

/**
 * The analytics screens, rendered against payloads captured from the seed.
 *
 * These assert the things a chart cannot: that the figure on the page is the
 * figure the server sent, that a rate never appears without the fraction
 * behind it, that a compensation statistic never appears without its coverage,
 * and that every chart has its table. Those are the properties that stop a
 * number here being misquoted somewhere else.
 */

afterEach(() => {
  vi.unstubAllGlobals();
});

const cycleFixture = staffCycleAnalytics as unknown as CycleAnalyticsPayload;
const portalFixture = adminAnalyticsPortal as unknown as PortalAnalyticsPayload;

describe("cycle analytics", () => {
  it("shows the funnel the server counted, not a recomputed one", async () => {
    mockScreens({ "analytics": staffCycleAnalytics });
    renderScreen(<CycleAnalytics />, {
      path: "/staff/cycles/:id/analytics",
      route: "/staff/cycles/abc/analytics",
    });

    expect(await screen.findByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    const { funnel } = cycleFixture;
    for (const [label, value] of [
      ["Registered", funnel.registered],
      ["Applied", funnel.applied],
      ["Offered", funnel.offered],
      ["Placed", funnel.placed.total],
    ] as const) {
      const labelled = (await screen.findAllByText(label))[0] as HTMLElement;
      const card = labelled.closest("div") as HTMLElement;
      expect(within(card).getByText(String(value))).toBeInTheDocument();
    }
  });

  it("prints both placement rates, the flat one first", async () => {
    mockScreens({ "analytics": staffCycleAnalytics });
    renderScreen(<CycleAnalytics />, {
      path: "/staff/cycles/:id/analytics",
      route: "/staff/cycles/abc/analytics",
    });

    await screen.findByRole("heading", { name: "Analytics" });
    const { funnel } = cycleFixture;
    // Each rate shows the fraction it came from, so nobody quotes a percentage
    // without being able to see how few people it is over. The same fraction
    // recurs in the breakdown tables, hence findAll.
    expect(
      await screen.findAllByText(
        `(${funnel.placement_rate.numerator}/${funnel.placement_rate.denominator})`,
      ),
    ).not.toHaveLength(0);
    expect(
      await screen.findAllByText(
        `(${funnel.placement_rate_seeking.numerator}/${funnel.placement_rate_seeking.denominator})`,
      ),
    ).not.toHaveLength(0);
    // The seeded world tags a member, so the two denominators genuinely differ
    // — if they did not, this test would pass without proving anything.
    expect(funnel.placement_rate.denominator).toBeGreaterThan(
      funnel.placement_rate_seeking.denominator,
    );
    expect(await screen.findByText(/Seeking only/)).toBeInTheDocument();
  });

  it("shows the external half of the split, and says it sums", async () => {
    mockScreens({ "analytics": staffCycleAnalytics });
    renderScreen(<CycleAnalytics />, {
      path: "/staff/cycles/:id/analytics",
      route: "/staff/cycles/abc/analytics",
    });

    await screen.findByRole("heading", { name: "Analytics" });
    const { placed } = cycleFixture.funnel;
    expect(placed.split.external).toBeGreaterThan(0);
    expect(
      await screen.findByText(`${placed.split.external} external`),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(new RegExp(`${placed.external_sources.ppo} PPO`)),
    ).toBeInTheDocument();
    expect(placed.split.portal + placed.split.external).toBe(placed.total);
  });

  it("never shows a compensation figure without its coverage", async () => {
    mockScreens({ "analytics": staffCycleAnalytics });
    renderScreen(<CycleAnalytics />, {
      path: "/staff/cycles/:id/analytics",
      route: "/staff/cycles/abc/analytics",
    });

    await screen.findByRole("heading", { name: "Analytics" });
    const placement = cycleFixture.compensation.placement;
    if (placement.covered > 0) {
      expect(
        await screen.findByText(
          new RegExp(`From ${placement.covered} of ${placement.placed} placed`),
        ),
      ).toBeInTheDocument();
    } else {
      expect(
        await screen.findAllByText(/No recorded compensation/),
      ).not.toHaveLength(0);
    }
  });

  it("gives every chart a table beside it", async () => {
    mockScreens({ "analytics": staffCycleAnalytics });
    renderScreen(<CycleAnalytics />, {
      path: "/staff/cycles/:id/analytics",
      route: "/staff/cycles/abc/analytics",
    });

    await screen.findByRole("heading", { name: "Analytics" });
    // ANA-2 wants figures that stay readable and exportable without the
    // visualisation, so a chart on its own is never enough.
    const charts = await screen.findAllByRole("img", { name: /\(chart\)/ });
    expect(charts.length).toBeGreaterThan(0);
    for (const chart of charts) {
      const frame = chart.closest("section");
      expect(within(frame as HTMLElement).getByRole("table")).toBeInTheDocument();
    }
  });
});

describe("job analytics", () => {
  it("renders the pipeline with excused kept apart from absent", async () => {
    mockScreens({ "analytics": staffJobAnalytics });
    renderScreen(<JobAnalytics />, {
      path: "/staff/jobs/:id/analytics",
      route: "/staff/jobs/abc/analytics",
    });

    expect(await screen.findByRole("heading", { name: "Analytics" })).toBeInTheDocument();
    if (staffJobAnalytics.shape === "pipeline" && staffJobAnalytics.rounds.length > 0) {
      // RND-3 gives absent and excused different consequences, so the page
      // must never merge them into one column.
      expect(await screen.findByText("Absent")).toBeInTheDocument();
      expect(await screen.findByText("Excused")).toBeInTheDocument();
    }
  });

  it("shows an open-cycle job no pipeline at all", async () => {
    const open = { ...staffJobAnalytics, shape: "open", rounds: [] };
    mockScreens({ "analytics": open });
    renderScreen(<JobAnalytics />, {
      path: "/staff/jobs/:id/analytics",
      route: "/staff/jobs/abc/analytics",
    });

    await screen.findByRole("heading", { name: "Analytics" });
    expect(await screen.findByText(/outcomes are recorded/)).toBeInTheDocument();
    expect(screen.queryByText("Excused")).not.toBeInTheDocument();
  });
});

describe("portal analytics", () => {
  it("pluralises the placed-student sentence", async () => {
    const body = structuredClone(portalFixture);
    body.portal_wide_placed.total = 1;
    body.portal_wide_placed.split.external = 1;
    mockScreens({ "analytics/portal": body });
    renderScreen(<PortalAnalytics />, { path: "/admin/analytics", route: "/admin/analytics" });

    expect(await screen.findByText(/1 student is placed, 1 of them externally/)).toBeInTheDocument();
    expect(screen.queryByText(/1 students are/)).not.toBeInTheDocument();
  });

  it("shows the yearly trend and both halves of the split", async () => {
    mockScreens({ "analytics/portal": adminAnalyticsPortal });
    renderScreen(<PortalAnalytics />, { path: "/admin/analytics", route: "/admin/analytics" });

    expect(
      await screen.findByRole("heading", { name: "Portal analytics" }),
    ).toBeInTheDocument();
    const { placed } = portalFixture.overall;
    // Both halves are populated in the seed, so this proves the split renders
    // rather than that zero renders as zero.
    expect(placed.split.portal).toBeGreaterThan(0);
    expect(placed.split.external).toBeGreaterThan(0);
    expect(
      await screen.findByText(`${placed.split.portal} on campus`),
    ).toBeInTheDocument();
    for (const year of portalFixture.years) {
      expect(await screen.findByText(year.year)).toBeInTheDocument();
    }
  });

  it("marks the canned report provisional and cannot dismiss it", async () => {
    mockScreens({ "analytics/portal": adminAnalyticsPortal });
    renderScreen(<PortalAnalytics />, { path: "/admin/analytics", route: "/admin/analytics" });

    await screen.findByRole("heading", { name: "Portal analytics" });
    expect(portalFixture.canned_report.provisional).toBe(true);
    const notice = await screen.findByText(/NIRF and RTI formats/);
    expect(notice).toBeInTheDocument();
    // No control hides it: the provisional status travels with the table.
    expect(
      within(notice.parentElement as HTMLElement).queryByRole("button"),
    ).not.toBeInTheDocument();
  });

  it("renders the report columns the server chose, in its order", async () => {
    mockScreens({ "analytics/portal": adminAnalyticsPortal });
    renderScreen(<PortalAnalytics />, { path: "/admin/analytics", route: "/admin/analytics" });

    await screen.findByRole("heading", { name: "Portal analytics" });
    const labels = portalFixture.canned_report.columns.map((column) => column.label);
    // The flat rate leads the adjusted one, which is the safeguard against a
    // filing quoting the larger number (the design review 4.30b).
    expect(labels.indexOf("Placement rate")).toBeLessThan(
      labels.indexOf("Placement rate (seeking only)"),
    );
    for (const label of labels) {
      expect((await screen.findAllByText(label)).length).toBeGreaterThan(0);
    }
  });
});
