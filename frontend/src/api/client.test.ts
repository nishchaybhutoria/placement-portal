import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { command, csrfToken, resolveScreenPath, screen } from "./client";
import { DomainRejectionError, ForbiddenError, UnauthenticatedError, ApiError } from "./problem";

function jsonResponse(body: unknown, init: ResponseInit = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
  });
}

function problemResponse(status: number, body: Record<string, unknown>): Response {
  return new Response(JSON.stringify({ status, ...body }), {
    status,
    headers: { "Content-Type": "application/problem+json" },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  document.cookie = "cds_csrf=token-123";
});

/** The nth fetch call, narrowed — `noUncheckedIndexedAccess` is on. */
function sentCall(index: number): [string, RequestInit] {
  const call = fetchMock.mock.calls[index];
  if (!call) throw new Error(`no fetch call at index ${index}`);
  return call as [string, RequestInit];
}

function sentBody(index: number): Record<string, unknown> {
  return JSON.parse(sentCall(index)[1].body as string) as Record<string, unknown>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = "cds_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("csrfToken", () => {
  it("reads the double-submit cookie", () => {
    expect(csrfToken()).toBe("token-123");
  });

  it("returns empty when the cookie is absent", () => {
    document.cookie = "cds_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
    expect(csrfToken()).toBe("");
  });
});

describe("resolveScreenPath", () => {
  it("passes through a screen with no params", () => {
    expect(resolveScreenPath("staff/cycles")).toBe("/api/v1/screens/staff/cycles");
  });

  it("substitutes and encodes path params", () => {
    expect(resolveScreenPath("staff/cycle/{id}", { id: "a b" })).toBe(
      "/api/v1/screens/staff/cycle/a%20b",
    );
  });

  it("throws rather than requesting a path with a literal placeholder", () => {
    expect(() => resolveScreenPath("staff/cycle/{id}")).toThrow(/requires a "id" param/);
  });
});

describe("command", () => {
  it("sends the envelope and the CSRF header", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ summary: { ok: true } }));
    await command("archive_cycle", { cycle_id: "c1" } as never);

    const [url, init] = sentCall(0);
    expect(url).toBe("/api/v1/commands/archive_cycle");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("same-origin");
    expect((init.headers as Record<string, string>)["X-CSRF"]).toBe("token-123");
    expect(JSON.parse(init.body as string)).toEqual({
      input: { cycle_id: "c1" },
      dry_run: false,
    });
  });

  it("omits idempotency_key unless one is given", async () => {
    // A Response body can only be read once, so build a fresh one per call.
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse({ summary: {} })));
    await command("archive_cycle", { cycle_id: "c1" } as never);
    expect(sentBody(0)).not.toHaveProperty("idempotency_key");

    await command("archive_cycle", { cycle_id: "c1" } as never, { idempotencyKey: "k1" });
    expect(sentBody(1)["idempotency_key"]).toBe("k1");
  });

  it("sets dry_run and returns the projected events", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ summary: { count: 2 }, events: [{ event_type: "x" }] }));
    const preview = await command("archive_cycle", { cycle_id: "c1" } as never, { dryRun: true });

    expect(sentBody(0)["dry_run"]).toBe(true);
    expect(preview.events).toHaveLength(1);
  });
});

describe("screen", () => {
  it("is a GET with no CSRF header and no body", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ rows: [] }));
    await screen("staff/cycles");

    const [, init] = sentCall(0);
    expect(init.method).toBe("GET");
    expect(init.body).toBeUndefined();
    expect(init.headers).not.toHaveProperty("X-CSRF");
  });

  it("appends query params and drops undefined ones", async () => {
    fetchMock.mockResolvedValue(jsonResponse({}));
    await screen("staff/cycles", undefined, { query: { page: 2, q: undefined, open: true } });
    expect(sentCall(0)[0]).toBe("/api/v1/screens/staff/cycles?page=2&open=true");
  });
});

describe("problem+json → typed errors", () => {
  it("maps 409 to DomainRejectionError and exposes the reasons", async () => {
    fetchMock.mockResolvedValue(
      problemResponse(409, {
        title: "Command rejected",
        reasons: [{ code: "cycle_archived", human: "This cycle is archived." }],
      }),
    );

    const error = await command("archive_cycle", { cycle_id: "c1" } as never).catch((e) => e);
    expect(error).toBeInstanceOf(DomainRejectionError);
    expect(error.reasons[0].code).toBe("cycle_archived");
  });

  it("maps 401 and 403 apart", async () => {
    fetchMock.mockImplementation(() =>
      Promise.resolve(problemResponse(401, { title: "Authentication required" })),
    );
    await expect(screen("staff/cycles")).rejects.toBeInstanceOf(UnauthenticatedError);

    fetchMock.mockImplementation(() => Promise.resolve(problemResponse(403, { title: "Forbidden" })));
    await expect(screen("staff/cycles")).rejects.toBeInstanceOf(ForbiddenError);
  });

  it("still reports the status when the body is not JSON", async () => {
    fetchMock.mockResolvedValue(
      new Response("<html>502</html>", { status: 502, headers: { "Content-Type": "text/html" } }),
    );

    const error = await screen("staff/cycles").catch((e) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(502);
    // The UI must never see a parse failure in place of the real status.
    expect(error.reasons).toHaveLength(1);
  });
});
