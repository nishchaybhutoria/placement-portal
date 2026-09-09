import type { AppliedOverride, TimelineEvent } from "@/api/payloads";
import { formatDateTime } from "@/lib/date";
import { humanise } from "@/lib/text";

/**
 * What an application event's payload says, in words.
 *
 * the design review §4.35 requires the meaningful part of a payload to be rendered and
 * not merely delivered, and the timeline is the surface it was written about
 * twice over: `apply` stamps `applied_override_ids` into the event exactly as
 * INT-2 demands, the screen sends it, and nothing rendered it. An override is
 * a staff member deliberately setting a rule aside for one student, and the
 * only question anyone asks afterwards is *why was this person allowed in*.
 *
 * Two rules follow, and neither is about overrides specifically:
 *
 * * **Ids are resolved, never shown.** The server resolves an override id into
 *   its domain, granter, date and reason — `payload_labels`, parallel to the
 *   payload the way `subject_labels` sits beside a finding's `subject`. The
 *   reason is rendered **inline**, not behind a disclosure: it is the
 *   load-bearing part of the row.
 * * **Nothing is dropped.** The payload also carries cascade causes, triggers,
 *   termination kinds and finding details. Known keys read as sentences; every
 *   other key stays in a compact disclosure, as the enrollment audit trail's
 *   details already do. A payload key nobody has taught this component about
 *   still reaches the reader.
 */
export function EventPayload({
  payload,
  labels,
}: {
  payload: Record<string, unknown> | null | undefined;
  labels?: TimelineEvent["payload_labels"];
}) {
  const entries = Object.entries(payload ?? {}).filter(
    ([key, value]) => !isEmpty(value) && key !== "applied_override_ids",
  );
  const overrides = labels?.applied_override_ids ?? [];
  const prose = entries
    // A formatter returns null when another key already says it — the two
    // halves of a status change are one sentence, not two.
    .map(([key, value]) => [key, PROSE[key]?.(value, payload ?? {}) ?? null] as const)
    .filter((row): row is readonly [string, string] => row[1] !== null);
  const remaining = entries.filter(([key]) => !(key in PROSE));

  if (overrides.length === 0 && prose.length === 0 && remaining.length === 0) {
    return null;
  }

  return (
    <div className="mt-gap-tight text-body-sm">
      {overrides.length > 0 ? (
        <ul aria-label="Overrides applied" className="flex flex-col gap-gap-tight text-foreground">
          {overrides.map((override) => (
            <li key={override.id}>{overrideSentence(override)}</li>
          ))}
        </ul>
      ) : null}
      {prose.length > 0 ? (
        <ul aria-label="What this event records" className="flex flex-col gap-gap-tight text-muted-foreground">
          {prose.map(([key, text]) => (
            <li key={key}>{text}</li>
          ))}
        </ul>
      ) : null}
      {remaining.length > 0 ? (
        <details className="mt-gap-tight text-muted-foreground">
          <summary className="cursor-pointer">Payload ({remaining.length})</summary>
          <dl className="mt-gap-tight grid gap-x-gap-lg gap-y-gap-tight sm:grid-cols-[max-content_1fr]">
            {remaining.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-medium text-foreground">{humanise(key)}</dt>
                <dd className="break-all">{formatValue(value)}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  );
}

/** INT-2's rule domains, as the gate that consulted them would say it. */
export const RULE_DOMAIN_LABELS: Record<string, string> = {
  eligibility: "Eligibility requirement",
  application_deadline: "Application deadline",
  edit_window: "Application edit window",
  withdraw_window: "Application withdrawal window",
  outcome_gate: "Placement outcome gate",
  offer_cap: "Offer cap",
  offer_deadline: "Offer response deadline",
  cycle_registration_window: "Cycle registration window",
  cycle_join_rule: "Cycle join requirement",
};

function overrideSentence(override: AppliedOverride): string {
  if (override.rule_domain === null) {
    // The grant is gone. Say that; printing the id it stood for answers
    // nobody's question, which is the whole point of resolving it.
    return "An override influenced this decision, and the grant is no longer available.";
  }
  const domain = RULE_DOMAIN_LABELS[override.rule_domain] ?? humanise(override.rule_domain);
  // `allow: false` is a grant that closes a gate rather than opening one —
  // the domain's `blocked_by_override` refusal — and reads the other way.
  const verdict = override.allow === false ? `${domain} closed` : `${domain} waived`;
  const by = override.granted_by ? ` by ${override.granted_by}` : "";
  const on = override.granted_at ? `, ${formatDateTime(override.granted_at)}` : "";
  const why = override.reason ? `, reason: ${override.reason}` : "";
  return `${verdict} — override granted${by}${on}${why}`;
}

/**
 * The payload keys that mean something to a reader, as sentences.
 *
 * A key is here because a dispute turns on it — what caused a cascade, whether
 * a person or the system did it, what a termination was, what a round
 * recorded. Everything else is honest in the disclosure, and adding a key here
 * is how a new one graduates into prose.
 */
const PROSE: Record<
  string,
  (value: unknown, payload: Record<string, unknown>) => string | null
> = {
  trigger: (value) => `Caused by ${humanise(String(value)).toLowerCase()}`,
  system_initiated: (value) =>
    value === true ? "Applied by the system, not by a person" : "Applied by a person",
  termination_kind: (value) => `Termination: ${humanise(String(value)).toLowerCase()}`,
  action: (value) => `Action: ${humanise(String(value)).toLowerCase()}`,
  operation: (value) => `Operation: ${humanise(String(value)).toLowerCase()}`,
  round: (value) => `Round: ${String(value)}`,
  round_result: (value) => `Result: ${humanise(String(value)).toLowerCase()}`,
  attendance: (value, payload) =>
    typeof payload.previous === "string"
      ? `Attendance: ${humanise(payload.previous).toLowerCase()} → ${humanise(String(value)).toLowerCase()}`
      : `Attendance: ${humanise(String(value)).toLowerCase()}`,
  // Stated inside the `attendance` sentence when both are present.
  previous: (value, payload) =>
    "attendance" in payload ? null : `Previously ${humanise(String(value)).toLowerCase()}`,
  strike_awarded: (value) => (value === true ? "A strike was awarded" : "No strike was awarded"),
  venue: (value) => `Venue: ${String(value)}`,
  scheduled_at: (value) => `Scheduled for ${formatDateTime(String(value))}`,
  deadline_at: (value) => `Deadline ${formatDateTime(String(value))}`,
  reschedule_at: (value) => `Rescheduled to ${formatDateTime(String(value))}`,
  answer_count: (value) => `${String(value)} answer${value === 1 ? "" : "s"} saved`,
  resume_changed: (value) => (value === true ? "The resume changed" : "The resume did not change"),
  notified: (value) => (value === true ? "The student was notified" : "The student was not notified"),
  failed_gate_codes: (value) => `Gates that failed: ${formatValue(value)}`,
  unperformed: (value) => `Consequences not performed: ${formatValue(value)}`,
  implicit_consequences: (value) => `Implicit consequences: ${formatValue(value)}`,
  from_external_status: (value, payload) =>
    `External offer: ${humanise(String(value)).toLowerCase()} → ${
      typeof payload.to_external_status === "string"
        ? humanise(payload.to_external_status).toLowerCase()
        : "—"
    }`,
  outcome: (value) => `Outcome: ${humanise(String(value)).toLowerCase()}`,
  source: (value) => `Source: ${humanise(String(value))}`,
  detail: (value) => String(value),
  // The destination is already inside the `from_external_status` sentence, and
  // a payload that carries only the destination still states it.
  to_external_status: (value, payload) =>
    typeof payload.from_external_status === "string"
      ? null
      : `External offer: ${humanise(String(value)).toLowerCase()}`,
};

function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined || value === "") return true;
  return Array.isArray(value) && value.length === 0;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) {
    return value.length === 0 ? "None" : value.map(formatValue).join(", ");
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, nested]) => `${humanise(key)}: ${formatValue(nested)}`)
      .join("; ");
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}
