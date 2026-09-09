import type { ReasonCode } from "@/lib/reasons";

/** One machine-readable rejection reason, mirroring `core/plan.Reason`. */
export interface Reason {
  code: ReasonCode | string;
  human: string;
  field?: string | null;
  context?: Record<string, unknown> | null;
}

/** RFC 7807 body as `core/errors._problem` emits it. */
export interface ProblemBody {
  type: string;
  title: string;
  status: number;
  detail?: string;
  reasons?: Reason[];
  [key: string]: unknown;
}

/**
 * Every non-2xx from the API surfaces as one of these. Callers discriminate on
 * the subclass, never on a status number scattered through components.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly problem: ProblemBody;
  readonly requestId: string | null;

  constructor(problem: ProblemBody) {
    super(problem.title || `HTTP ${problem.status}`);
    this.name = "ApiError";
    this.status = problem.status;
    this.problem = problem;
    this.requestId = typeof problem.request_id === "string" ? problem.request_id : null;
  }

  /** Reasons if the server sent structured ones, else a single synthetic reason. */
  get reasons(): Reason[] {
    return this.problem.reasons?.length
      ? this.problem.reasons
      : [{ code: "unknown", human: this.problem.detail ?? this.message }];
  }
}

/** 409 — the command was understood and refused. Render `reasons`, not a stack. */
export class DomainRejectionError extends ApiError {
  constructor(problem: ProblemBody) {
    super(problem);
    this.name = "DomainRejectionError";
  }
}

/** 401 — no session, or it expired. The router redirects to login on this. */
export class UnauthenticatedError extends ApiError {
  constructor(problem: ProblemBody) {
    super(problem);
    this.name = "UnauthenticatedError";
  }
}

/** 403 — authenticated but out of scope. Distinct from 401: do not redirect. */
export class ForbiddenError extends ApiError {
  constructor(problem: ProblemBody) {
    super(problem);
    this.name = "ForbiddenError";
  }
}

/** 429 — the registry rate limit fired. */
export class RateLimitedError extends ApiError {
  constructor(problem: ProblemBody) {
    super(problem);
    this.name = "RateLimitedError";
  }
}

/** 422 — request shape rejected before the command ran. */
export class ValidationError extends ApiError {
  constructor(problem: ProblemBody) {
    super(problem);
    this.name = "ValidationError";
  }
}

/**
 * Build the right error subclass from a response.
 *
 * A body that is not problem+json (a proxy 502, an HTML error page) still has
 * to become an ApiError — the UI must never see a raw parse failure in place of
 * the actual status.
 */
export async function toApiError(response: Response): Promise<ApiError> {
  let problem: ProblemBody;
  try {
    const parsed: unknown = await response.json();
    problem =
      parsed && typeof parsed === "object"
        ? { status: response.status, type: "about:blank", title: response.statusText, ...parsed }
        : { status: response.status, type: "about:blank", title: response.statusText };
  } catch {
    problem = {
      status: response.status,
      type: "about:blank",
      title: response.statusText || "Request failed",
    };
  }

  const requestId = response.headers.get("x-request-id");
  if (requestId) problem.request_id = requestId;

  switch (response.status) {
    case 401:
      return new UnauthenticatedError(problem);
    case 403:
      return new ForbiddenError(problem);
    case 409:
      return new DomainRejectionError(problem);
    case 422:
      return new ValidationError(problem);
    case 429:
      return new RateLimitedError(problem);
    default:
      return new ApiError(problem);
  }
}
