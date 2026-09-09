import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Every route has a render test, and adding one without a test fails here.
 *
 * The hand-maintained list in `screens.test.tsx` was complete when this was
 * written — that is exactly when a ratchet is worth adding, because it costs
 * nothing to satisfy today and is the only thing that keeps it complete
 * tomorrow. It is the frontend counterpart of the backend's authz matrix and
 * screen-execution ratchets, both of which assert the fixture set *equals* the
 * registry rather than being a subset of it.
 *
 * What it proves is narrow and worth stating: that some test mounts the
 * component a route points at. It does not prove the test asserts anything
 * meaningful — §4.35 already established that screen execution and component
 * rendering are different boundaries, and this is a third, weaker one. A
 * screen with a render test that asserts nothing passes this and deserves to
 * fail review.
 */

const root = resolve(process.cwd(), "src");
const app = readFileSync(resolve(root, "App.tsx"), "utf8");
const tests = ["screens.test.tsx", "refusedStaffScreens.test.tsx", "auditScreens.test.tsx"]
  .map((name) => readFileSync(resolve(root, "screens", name), "utf8"))
  .concat(readFileSync(resolve(root, "screens/analytics/analytics.test.tsx"), "utf8"))
  .join("\n");

/**
 * Layout and plumbing, not screens. `Deferred` is the Suspense wrapper the
 * analytics routes sit inside, so reading only the *first* component name in
 * an element expression would report the wrapper and miss the screen.
 */
const NOT_SCREENS = new Set(["AppLayout", "Navigate", "RequireAuth", "Outlet", "Deferred"]);

/** Every screen component a route can mount, wrappers unwrapped. */
function routes(): { path: string; components: string[] }[] {
  const pattern = /<Route\s+path="([^"]*)"\s+element=\{([\s\S]*?)\}\s*\/?>/g;
  const found: { path: string; components: string[] }[] = [];
  for (const match of app.matchAll(pattern)) {
    const [, path, element] = match;
    if (path === undefined || element === undefined) continue;
    const components = [...element.matchAll(/<([A-Z]\w*)/g)]
      .map((inner) => inner[1] as string)
      .filter((name) => !NOT_SCREENS.has(name));
    found.push({ path, components });
  }
  return found;
}

describe("route render coverage", () => {
  it("finds the routes at all, so a rename cannot silently empty this test", () => {
    // The regex is the weak point: if App.tsx's route syntax changes, this
    // suite would pass by matching nothing. Pin a floor instead.
    expect(routes().length).toBeGreaterThanOrEqual(25);
  });

  it("mounts every routed screen in some render test", () => {
    const missing = routes()
      .filter(({ components }) => components.length > 0)
      .filter(
        ({ components }) =>
          !components.some((name) => new RegExp(`<${name}\\s*/>`).test(tests)),
      )
      .map(({ path, components }) => `${components.join("/")} (route "${path}")`);

    expect(missing, "routed screens with no render test").toEqual([]);
  });
});
