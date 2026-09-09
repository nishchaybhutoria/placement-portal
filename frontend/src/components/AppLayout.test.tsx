import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Me } from "@/api/client";
import { renderScreen } from "@/test/harness";
import { AppLayout } from "./AppLayout";

const ADMIN: Me = {
  authenticated: true,
  dev_login_enabled: false,
  user: { id: "u1", email: "admin@example.edu", full_name: "CDS Administrator", role: "admin" },
  coordinated_cycle_ids: [],
};

describe("AppLayout", () => {
  /**
   * WCAG 2.4.1. An admin's rail is thirteen links and it precedes the page on
   * every route, so the bypass has to exist and has to point at something that
   * can actually take focus — an anchor to a missing id looks right and does
   * nothing.
   */
  it("offers a skip link before the nav, targeting a focusable main", () => {
    const { container } = renderScreen(<AppLayout me={ADMIN} />);

    const skip = screen.getByRole("link", { name: "Skip to content" });
    expect(skip).toHaveAttribute("href", "#main-content");

    const main = container.querySelector("main");
    expect(main).not.toBeNull();
    expect(main).toHaveAttribute("id", "main-content");
    // Without this the browser scrolls but leaves focus in the nav.
    expect(main).toHaveAttribute("tabindex", "-1");

    // First in the DOM, or it is not a bypass: everything the rail renders has
    // to come after it.
    const focusable = Array.from(container.querySelectorAll("a[href], button"));
    expect(focusable[0]).toBe(skip);
  });
});
