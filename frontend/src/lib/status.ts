import { humanise } from "./text";

/**
 * Status-chip mapping — the data form of `docs/design/DESIGN.md` §4.
 *
 * DRAFT: the mapping itself is pending review (see DESIGN.md §0.3). The shape
 * here is stable; the family assignments may change.
 *
 * The load-bearing rule: red is reserved for outcomes imposed on the student,
 * never for choices the student made freely — `declined` and `withdrawn` are
 * `neutral`, `rejected` and `removed` are `danger`.
 */
export const SEMANTIC_FAMILIES = [
  "success",
  "warning",
  "danger",
  "info",
  "neutral",
  "brand",
] as const;

export type SemanticFamily = (typeof SEMANTIC_FAMILIES)[number];

export interface StatusMeta {
  readonly label: string;
  readonly family: SemanticFamily;
}

/** `application_status_t` — LLD §6. */
export const APPLICATION_STATUS = {
  in_progress: { label: "In progress", family: "info" },
  pending_offer: { label: "Pending offer", family: "warning" },
  offered: { label: "Offered", family: "brand" },
  accepted: { label: "Accepted", family: "success" },
  declined: { label: "Declined", family: "neutral" },
  rejected: { label: "Rejected", family: "danger" },
  withdrawn: { label: "Withdrawn", family: "neutral" },
  auto_withdrawn: { label: "Auto-withdrawn", family: "warning" },
  offer_terminated: { label: "Offer terminated", family: "danger" },
} as const satisfies Record<string, StatusMeta>;

/** `attendance_t` — LLD §6. */
export const ATTENDANCE_STATUS = {
  pending: { label: "Pending", family: "info" },
  present: { label: "Present", family: "success" },
  absent: { label: "Absent", family: "danger" },
  excused: { label: "Excused", family: "neutral" },
} as const satisfies Record<string, StatusMeta>;

/** `round_result_t` — LLD §6, needed by the board from M10b. */
export const ROUND_RESULT = {
  pending: { label: "Pending", family: "info" },
  advanced: { label: "Advanced", family: "success" },
  eliminated: { label: "Eliminated", family: "danger" },
  waitlisted: { label: "Waitlisted", family: "warning" },
} as const satisfies Record<string, StatusMeta>;

/** `membership_status_t` — LLD §6. */
export const MEMBERSHIP_STATUS = {
  pending: { label: "Pending", family: "warning" },
  active: { label: "Active", family: "success" },
  rejected: { label: "Rejected", family: "danger" },
  withdrawn: { label: "Withdrawn", family: "neutral" },
  removed: { label: "Removed", family: "danger" },
} as const satisfies Record<string, StatusMeta>;

export type ApplicationStatus = keyof typeof APPLICATION_STATUS;
export type AttendanceStatus = keyof typeof ATTENDANCE_STATUS;
export type MembershipStatus = keyof typeof MEMBERSHIP_STATUS;
export type RoundResult = keyof typeof ROUND_RESULT;

/** `external_status_t` — read-only for students, staff-recorded in M12. */
export const EXTERNAL_STATUS = {
  offered: { label: "Offered", family: "brand" },
  accepted: { label: "Accepted", family: "success" },
  declined: { label: "Declined", family: "neutral" },
} as const satisfies Record<string, StatusMeta>;

/** An override's live state — INT-2. `is_active` alone cannot say this: a row
 * with a past expiry is inert while its flag still reads true. */
export const OVERRIDE_STATE = {
  active: { label: "Active", family: "success" },
  expired: { label: "Expired", family: "neutral" },
  shadowed: { label: "Shadowed", family: "warning" },
  deactivated: { label: "Deactivated", family: "neutral" },
} as const satisfies Record<string, StatusMeta>;

/** `finding_status_t` — the consistency checker's verdicts (LLD §12). */
export const FINDING_STATUS = {
  open: { label: "Open", family: "danger" },
  resolved: { label: "Resolved", family: "success" },
  dismissed: { label: "Dismissed", family: "neutral" },
} as const satisfies Record<string, StatusMeta>;

/**
 * `notif_status_t` — delivery, as the student's own record shows it (LLD §18).
 *
 * The imposed-outcome rule applies as it does everywhere else. `failed` is a
 * warning because delivery retries; `dead` is danger because it does not, and
 * a notice that gave up is a thing that happened *to* the student — they were
 * never told, and they are reading this screen to find that out.
 */
export const NOTIFICATION_STATUS = {
  queued: { label: "Queued", family: "info" },
  sent: { label: "Sent", family: "success" },
  failed: { label: "Retrying", family: "warning" },
  dead: { label: "Not delivered", family: "danger" },
} as const satisfies Record<string, StatusMeta>;

export type StatusDomain =
  | "application"
  | "attendance"
  | "membership"
  | "round"
  | "external"
  | "override"
  | "finding"
  | "notification";

const DOMAINS: Record<StatusDomain, Record<string, StatusMeta>> = {
  application: APPLICATION_STATUS,
  attendance: ATTENDANCE_STATUS,
  membership: MEMBERSHIP_STATUS,
  round: ROUND_RESULT,
  external: EXTERNAL_STATUS,
  override: OVERRIDE_STATE,
  finding: FINDING_STATUS,
  notification: NOTIFICATION_STATUS,
};

/** Humanise an unmapped value rather than rendering a raw enum token. */
function fallback(value: string): StatusMeta {
  return { label: humanise(value), family: "neutral" };
}

export function statusMeta(domain: StatusDomain, value: string): StatusMeta {
  return DOMAINS[domain][value] ?? fallback(value);
}
