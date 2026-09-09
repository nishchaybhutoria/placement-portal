import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import type { ReactElement } from "react";
import { vi } from "vitest";

/**
 * Render one screen against the payloads the server actually sends.
 *
 * The fixtures under `fixtures/` are captured verbatim from a seeded database
 * (`python -m app.seed`, then each screen fetched as the right actor), so a
 * screen that reads a field the server does not send fails here rather than in
 * front of somebody. They are refreshed by re-running that capture; they are
 * not hand-written, which is the point — a hand-written fixture only proves the
 * component agrees with itself.
 */
export interface MockedFetch {
  /** Every request the screen made, in order. */
  calls: { url: string; init?: RequestInit }[];
  /** The parsed bodies posted to one command, oldest first. */
  posted(command: string): Record<string, unknown>[];
}

export function mockScreens(routes: Record<string, unknown>): MockedFetch {
  const calls: { url: string; init?: RequestInit }[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : String(input);
      calls.push(init === undefined ? { url } : { url, init });
      for (const [suffix, body] of Object.entries(routes)) {
        if (url.includes(suffix)) {
          return Promise.resolve(
            new Response(JSON.stringify(body), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          );
        }
      }
      return Promise.resolve(
        new Response(JSON.stringify({ status: 404, title: "Not found" }), {
          status: 404,
          headers: { "Content-Type": "application/problem+json" },
        }),
      );
    }),
  );
  return {
    calls,
    posted(command) {
      return calls
        .filter((call) => call.url.includes(`commands/${command}`))
        .map(
          (call) =>
            (JSON.parse(String(call.init?.body ?? "{}")) as {
              input?: Record<string, unknown>;
            }).input ?? {},
        );
    },
  };
}

export function renderScreen(
  element: ReactElement,
  { path = "/", route = "/" }: { path?: string; route?: string } = {},
): RenderResult {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter
        initialEntries={[route]}
      >
        <Routes>
          <Route path={path} element={element} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
