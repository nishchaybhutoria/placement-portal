import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, test } from "@playwright/test";

/**
 * Every screen at a phone width, which no gate covered until now.
 *
 * The mechanics were already right — `AppLayout` hides the sidebar below `lg`
 * and swaps in a dialog nav, and `DataTable` wraps every table in its own
 * `overflow-x-auto` with the comment "wide tables scroll inside their own
 * container; the page never does". What was missing was the observation:
 * `playwright.config.ts` ran Desktop Chrome and nothing else, so "the student
 * screens work at 390px" was an inference from the CSS rather than something
 * anybody had seen. Twelve screens carry no responsive prefixes at all, which
 * is fine for a single-column list and is exactly where a real pass finds
 * something.
 *
 * The load-bearing assertion is that the *page* never scrolls sideways. A
 * table that scrolls inside its container is the design; a page that scrolls
 * under a fixed header is a bug you cannot read your way out of on a phone.
 *
 * 390x844 is the iPhone 12/13/14 logical viewport and the narrowest width
 * worth supporting; anything narrower is a rounding error in the market.
 */

test.use({ viewport: { width: 390, height: 844 } });

const STUDENT_EMAIL = "e2e.student@example.edu";
const COORDINATOR_EMAIL = "coordinator@example.edu";

async function login(page: Page, email: string) {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
  await page.getByRole("textbox", { name: "Email" }).fill(email);
  await page.getByRole("button", { name: "Sign in as this user" }).click();
  // Not "Sign out": below `lg` the rail is gone and `Account` — the theme
  // control and Sign out with it — lives inside the nav dialog. The hamburger
  // is the whole mobile chrome, which is why it is the signal that the app has
  // loaded and the first thing the nav test presses.
  await expect(page.getByRole("button", { name: "Open navigation" })).toBeVisible();
}

/** The page's own horizontal overflow, in CSS pixels. */
async function pageOverflow(page: Page): Promise<number> {
  return page.evaluate(() => {
    const root = document.documentElement;
    return Math.max(
      root.scrollWidth - root.clientWidth,
      document.body.scrollWidth - root.clientWidth,
    );
  });
}

async function visit(page: Page, path: string, heading: RegExp | string) {
  await page.goto(path);
  await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
  // One pixel of slack: sub-pixel layout rounding is not a horizontal scroll.
  expect(await pageOverflow(page), `${path} scrolls horizontally at 390px`).toBeLessThanOrEqual(1);
}

test("the student surface fits a phone", async ({ page }) => {
  await login(page, STUDENT_EMAIL);

  // The nav is the first thing that has to work: below `lg` the sidebar is
  // gone, and every page and the sign-out with it are unreachable without it.
  await page.getByRole("button", { name: "Open navigation" }).click();
  const nav = page.getByRole("dialog");
  await expect(nav.getByRole("link", { name: "Dashboard" })).toBeVisible();
  await expect(nav.getByRole("button", { name: "Sign out" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(nav).toBeHidden();

  await visit(page, "/dashboard", /Dashboard/i);
  await visit(page, "/cycles", /Cycles/i);
  await visit(page, "/applications", /applications/i);
  await visit(page, "/profile", /Profile/i);
});

test("the staff surface fits a phone", async ({ page }) => {
  await login(page, COORDINATOR_EMAIL);

  // The widest tables in the product live behind these three, which is why
  // they are the ones worth asserting rather than a sample of the simple ones.
  await visit(page, "/staff/cycles", /cycles/i);
  await visit(page, "/staff/companies", /Companies/i);
  await visit(page, "/staff/external", /external/i);
});

test("a wide table scrolls inside itself and never takes the page with it", async ({
  page,
}) => {
  await login(page, COORDINATOR_EMAIL);
  await page.goto("/staff/companies");
  await expect(page.getByRole("heading", { name: /Companies/ }).first()).toBeVisible();

  // The container is allowed to scroll — that is the design. The page is not.
  const scrollable = await page.evaluate(() => {
    const candidates = [...document.querySelectorAll("*")];
    return candidates.filter((element) => element.scrollWidth > element.clientWidth + 1)
      .length;
  });
  expect(scrollable).toBeGreaterThan(0);
  expect(await pageOverflow(page)).toBeLessThanOrEqual(1);
});

/**
 * A standing accessibility floor, computed from the rendered DOM.
 *
 * axe checks what a machine can check — a control with no accessible name, a
 * contrast pair below AA, a missing landmark, duplicate ids, malformed ARIA.
 * It cannot tell you a label is *wrong*, only that one is missing, so this is
 * a floor and not a substitute for the manual pass. It would have caught the
 * missing skip link that had to be found by hand.
 *
 * Scoped to serious and critical violations: the moderate/minor bands are
 * mostly best-practice advice, and a gate that fails on advice gets muted.
 */
const AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

async function auditable(page: Page, path: string) {
  await page.goto(path);
  await expect(page.getByRole("heading").first()).toBeVisible();
  const { violations } = await new AxeBuilder({ page }).withTags(AXE_TAGS).analyze();
  const serious = violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );
  expect(
    serious.map((violation) => `${violation.id} on ${violation.nodes.length} node(s): ${violation.help}`),
    `${path} has serious accessibility violations`,
  ).toEqual([]);
}

test("the student surface clears the accessibility floor", async ({ page }) => {
  await login(page, STUDENT_EMAIL);
  for (const path of ["/dashboard", "/cycles", "/applications", "/profile"]) {
    await auditable(page, path);
  }
});

test("the staff surface clears the accessibility floor", async ({ page }) => {
  await login(page, COORDINATOR_EMAIL);
  for (const path of ["/staff/cycles", "/staff/companies", "/staff/external"]) {
    await auditable(page, path);
  }
});
