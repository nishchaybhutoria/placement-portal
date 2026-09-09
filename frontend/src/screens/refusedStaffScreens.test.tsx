import { screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { renderScreen } from "@/test/harness";

import { CycleAnalytics } from "./analytics/CycleAnalytics";
import { JobAnalytics } from "./analytics/JobAnalytics";
import { Approvals } from "./cycles/Approvals";
import { CycleJobs } from "./jobs/CycleJobs";
import { JobBoard } from "./jobs/JobBoard";
import { JobBuilder } from "./jobs/JobBuilder";
import { CycleExternal } from "./offers/CycleExternal";
import { Offers } from "./offers/Offers";

interface RefusedScreen {
  name: string;
  element: ReactElement;
  path: string;
  route: string;
}

const REFUSED_SCREENS: RefusedScreen[] = [
  {
    name: "cycle jobs",
    element: <CycleJobs />,
    path: "/staff/cycles/:id/jobs",
    route: "/staff/cycles/cycle-id/jobs",
  },
  {
    name: "cycle approvals",
    element: <Approvals />,
    path: "/staff/cycles/:id/approvals",
    route: "/staff/cycles/cycle-id/approvals",
  },
  {
    name: "cycle external offers",
    element: <CycleExternal />,
    path: "/staff/cycles/:id/external",
    route: "/staff/cycles/cycle-id/external",
  },
  {
    name: "cycle analytics",
    element: <CycleAnalytics />,
    path: "/staff/cycles/:id/analytics",
    route: "/staff/cycles/cycle-id/analytics",
  },
  {
    name: "job builder",
    element: <JobBuilder />,
    path: "/staff/jobs/:id",
    route: "/staff/jobs/job-id?cycle_id=cycle-id",
  },
  {
    name: "job board",
    element: <JobBoard />,
    path: "/staff/jobs/:id/board",
    route: "/staff/jobs/job-id/board",
  },
  {
    name: "job offers",
    element: <Offers />,
    path: "/staff/jobs/:id/offers",
    route: "/staff/jobs/job-id/offers",
  },
  {
    name: "job analytics",
    element: <JobAnalytics />,
    path: "/staff/jobs/:id/analytics",
    route: "/staff/jobs/job-id/analytics",
  },
];

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the design review §4.40 refused staff sub-resource screens", () => {
  it.each(REFUSED_SCREENS)("lets the refusal own the whole $name page", async (entry) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() =>
        Promise.resolve(
          new Response(
            JSON.stringify({
              type: "about:blank",
              title: "Forbidden",
              status: 403,
              detail: "This cycle is outside your access.",
            }),
            {
              status: 403,
              headers: { "Content-Type": "application/problem+json" },
            },
          ),
        ),
      ),
    );

    renderScreen(entry.element, { path: entry.path, route: entry.route });

    expect(await screen.findByRole("alert")).toHaveTextContent("You cannot access this page");
    // The refusal supplies only its own recovery affordances. In particular,
    // no page heading, create/export button, tab, filter, or sub-resource link
    // survives around a screen the server refused.
    expect(screen.queryAllByRole("heading")).toHaveLength(0);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Back to home" })).toBeInTheDocument();
  });
});
