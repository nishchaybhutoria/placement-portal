import type { paths } from "./gen/schema";
import { toApiError } from "./problem";

/* --------------------------------------------------------------------------
 * Types derived from the generated schema.
 *
 * These are the reason the generated client is committed: a command renamed or
 * a field retyped in the backend becomes a *frontend compile error*, not a
 * runtime 422 discovered by a student.
 * ------------------------------------------------------------------------ */

const COMMAND_PREFIX = "/api/v1/commands/";
const SCREEN_PREFIX = "/api/v1/screens/";

type CommandPath = Extract<keyof paths, `${typeof COMMAND_PREFIX}${string}`>;
type ScreenPath = Extract<keyof paths, `${typeof SCREEN_PREFIX}${string}`>;

/** e.g. `"join_cycle"` — every command the backend registry exposes. */
export type CommandName = CommandPath extends `${typeof COMMAND_PREFIX}${infer N}` ? N : never;
/** e.g. `"staff/cycle/{id}"` — every screen id, path params included. */
export type ScreenId = ScreenPath extends `${typeof SCREEN_PREFIX}${infer N}` ? N : never;

type Json = "application/json";

type CommandBody<N extends CommandName> =
  paths[`${typeof COMMAND_PREFIX}${N}`] extends { post: { requestBody: { content: Record<Json, infer B> } } }
    ? B
    : never;

/** The `input` field of a command's request envelope. */
export type CommandInput<N extends CommandName> = CommandBody<N> extends { input: infer I } ? I : never;

type CommandResponse<N extends CommandName> =
  paths[`${typeof COMMAND_PREFIX}${N}`] extends {
    post: { responses: { 200: { content: Record<Json, infer R> } } };
  }
    ? R
    : never;

/** The `summary` a command returns on execute. */
export type CommandSummary<N extends CommandName> =
  CommandResponse<N> extends { summary: infer S } ? S : never;

/** A dry-run result: the same summary, plus the events execution *would* emit. */
export interface Preview<N extends CommandName> {
  summary: CommandSummary<N>;
  events: PreviewEvent[];
}

/** One projected event from a dry run — the payload `<PreviewConfirm>` renders. */
export interface PreviewEvent {
  application_id: string | null;
  event_type: string;
  from_status: string | null;
  to_status: string | null;
  from_round: string | null;
  to_round: string | null;
  reason: string | null;
  payload: Record<string, unknown>;
}

export type ScreenData<I extends ScreenId> =
  paths[`${typeof SCREEN_PREFIX}${I}`] extends {
    get: { responses: { 200: { content: Record<Json, infer R> } } };
  }
    ? R
    : never;

/* --------------------------------------------------------------------------
 * CSRF
 * ------------------------------------------------------------------------ */

const CSRF_COOKIE = "cds_csrf";
const CSRF_HEADER = "X-CSRF";

/**
 * Read the double-submit CSRF token the server set (`identity/session.py`).
 *
 * The session cookie itself is httpOnly and deliberately unreadable here; this
 * one is not, which is the whole mechanism — we echo it back in a header that
 * a cross-site form post cannot set.
 */
export function csrfToken(): string {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]*)`));
  return match?.[1] ? decodeURIComponent(match[1]) : "";
}

/* --------------------------------------------------------------------------
 * Wrappers
 * ------------------------------------------------------------------------ */

export interface CommandOptions {
  /** Ask for the plan without applying it. Drives `<PreviewConfirm>`. */
  dryRun?: boolean;
  /** Replay guard. Send the *same* key for a retry of the same intent. */
  idempotencyKey?: string;
  signal?: AbortSignal;
}

/** Substitute `{id}`-style params into a screen id. Unfilled params throw. */
export function resolveScreenPath(id: ScreenId, params?: Record<string, string>): string {
  const filled = id.replace(/\{(\w+)\}/g, (_match, key: string) => {
    const value = params?.[key];
    if (value === undefined) {
      throw new Error(`screen "${id}" requires a "${key}" param`);
    }
    return encodeURIComponent(value);
  });
  return SCREEN_PREFIX + filled;
}

async function request<T>(url: string, init: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    // The session is a cookie; it must ride along on every call.
    credentials: "same-origin",
    headers: { Accept: "application/json", ...init.headers },
  });
  if (!response.ok) {
    throw await toApiError(response);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

/**
 * Execute a command.
 *
 * Overloaded so `dryRun: true` returns `Preview<N>` (summary + events) while a
 * real execution returns just the summary — the caller cannot read `.events`
 * off a live execution, because the server does not send them.
 */
export function command<N extends CommandName>(
  name: N,
  input: CommandInput<N>,
  options: CommandOptions & { dryRun: true },
): Promise<Preview<N>>;
export function command<N extends CommandName>(
  name: N,
  input: CommandInput<N>,
  options?: CommandOptions,
): Promise<{ summary: CommandSummary<N> }>;
export function command<N extends CommandName>(
  name: N,
  input: CommandInput<N>,
  options: CommandOptions = {},
): Promise<unknown> {
  const body: Record<string, unknown> = { input, dry_run: options.dryRun ?? false };
  if (options.idempotencyKey !== undefined) {
    body["idempotency_key"] = options.idempotencyKey;
  }
  return request(COMMAND_PREFIX + name, {
    method: "POST",
    headers: { "Content-Type": "application/json", [CSRF_HEADER]: csrfToken() },
    body: JSON.stringify(body),
    ...(options.signal ? { signal: options.signal } : {}),
  });
}

/** Read a screen. Screens are pure reads — no CSRF header, no body. */
export function screen<I extends ScreenId>(
  id: I,
  params?: Record<string, string>,
  options: { query?: Record<string, string | number | boolean | undefined>; signal?: AbortSignal } = {},
): Promise<ScreenData<I>> {
  const path = resolveScreenPath(id, params);
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(options.query ?? {})) {
    if (value !== undefined) query.set(key, String(value));
  }
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return request<ScreenData<I>>(path + suffix, {
    method: "GET",
    ...(options.signal ? { signal: options.signal } : {}),
  });
}

/* --------------------------------------------------------------------------
 * Bootstrap (`GET /me` — a plain route, not a registry screen)
 * ------------------------------------------------------------------------ */

export interface Me {
  authenticated: boolean;
  dev_login_enabled: boolean;
  user?: { id: string; email: string; full_name: string | null; role: "student" | "admin" };
  current_enrollment_id?: string | null;
  profile_declared?: boolean;
  coordinated_cycle_ids?: string[];
}

export function me(): Promise<Me> {
  return request<Me>("/me", { method: "GET" });
}

/**
 * Dev-only sign-in.
 *
 * `dev_login` is registered only when `DEV_LOGIN=true`, so it is absent from
 * the OpenAPI document the client is generated from and cannot go through the
 * typed `command()` wrapper. This is the one deliberately untyped call in the
 * app; it is reachable only when `/me` reports `dev_login_enabled`.
 */
export async function devLogin(email: string): Promise<void> {
  await request<unknown>(COMMAND_PREFIX + "dev_login", {
    method: "POST",
    headers: { "Content-Type": "application/json", [CSRF_HEADER]: csrfToken() },
    body: JSON.stringify({ input: { email }, dry_run: false }),
  });
}

/* --------------------------------------------------------------------------
 * Uploads (parse-only routes — they write nothing)
 * ------------------------------------------------------------------------ */

/** One row of a venue/timing upload, in the shape the command consumes. */
export interface VenueUploadRow {
  row_number: number;
  identifier: string;
  venue: string;
  time: string;
}

/** A problem the parser found, named by row (the design review §4.5). */
export interface VenueUploadProblem {
  row_number: number | null;
  code: string;
  human: string;
  path: string | null;
}

export interface VenueUpload {
  rows: VenueUploadRow[];
  errors: VenueUploadProblem[];
  headers: string[];
}

/**
 * Parse a venue/timing spreadsheet into command rows.
 *
 * Multipart, so it cannot go through the typed `command()` wrapper; the route
 * is parse-only and writes nothing, and `assign_venue_timing` re-validates
 * every row it is handed — the upload is a convenience, never an authority.
 */
export function uploadVenueRows(file: File, signal?: AbortSignal): Promise<VenueUpload> {
  const form = new FormData();
  form.append("file", file);
  return request<VenueUpload>("/api/v1/uploads/venue-rows", {
    method: "POST",
    headers: { [CSRF_HEADER]: csrfToken() },
    body: form,
    ...(signal ? { signal } : {}),
  });
}

export interface ProfileUploadRow {
  row_number: number;
  institute_email: string;
  fields: Record<string, unknown>;
}

export interface ProfileUpload {
  rows: ProfileUploadRow[];
  errors: VenueUploadProblem[];
  headers: string[];
}

/** Parse a profile spreadsheet without writing anything. */
export function uploadProfileRows(file: File, signal?: AbortSignal): Promise<ProfileUpload> {
  const form = new FormData();
  form.append("file", file);
  return request<ProfileUpload>("/api/v1/uploads/profile-rows", {
    method: "POST",
    headers: { [CSRF_HEADER]: csrfToken() },
    body: form,
    ...(signal ? { signal } : {}),
  });
}

export const api = {
  command,
  screen,
  me,
  devLogin,
  csrfToken,
  resolveScreenPath,
  uploadVenueRows,
  uploadProfileRows,
};
