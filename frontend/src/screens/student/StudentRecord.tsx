import { useNavigate, useParams } from "react-router-dom";

import type { CommandInput } from "@/api/client";
import { payload, type StudentRecordPayload, type TimelineEvent } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { EventPayload } from "@/components/EventPayload";
import { ReinstatementPlan } from "@/components/CommandSummaryDetails";
import { SubjectOverrides } from "@/components/SubjectOverrides";
import { PreviewConfirm, type Choice } from "@/components/PreviewConfirm";
import { GrantOverride, overrideChoices } from "@/components/GrantOverride";
import { MembershipExit } from "@/components/MembershipExit";
import { OutcomeTag } from "@/components/OutcomeTag";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/input";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { StatusChip } from "@/components/ui/statusChip";
import { DataTable, type Column } from "@/components/ui/table";
import { formatDateTime, formatZonedDateTime } from "@/lib/date";
import type { ApplicationStatus } from "@/lib/status";
import { counted, humanise } from "@/lib/text";

const APPLICATION_STATUSES = [
  "in_progress",
  "pending_offer",
  "offered",
  "accepted",
  "declined",
  "rejected",
  "withdrawn",
  "auto_withdrawn",
  "offer_terminated",
] as const;

/** The complete staff record for one enrollment (Behavior INT-1, LLD §11.3). */
export function StudentRecord() {
  const { enrollmentId = "" } = useParams();
  const navigate = useNavigate();
  const screen = useScreen("staff/student/{enrollment_id}", {
    params: { enrollment_id: enrollmentId },
    enabled: enrollmentId !== "",
  });

  if (screen.isPending) return <ScreenSkeleton variant="detail" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<StudentRecordPayload>(screen.data);
  if (!data.enrollment) {
    return <EmptyState message="That enrollment no longer exists." />;
  }

  return (
    <>
      <PageHeader
        title={data.enrollment.full_name}
        subtitle={`${data.enrollment.roll_number ? `${data.enrollment.roll_number} · ` : ""}${data.enrollment.email}`}
        actions={
          <>
            <EditProfile data={data} enrollmentId={enrollmentId} />
            <GrantOverride
              scope={{ enrollment_id: enrollmentId }}
              title={`Grant ${data.enrollment.full_name} an override?`}
              description="A standing exception for this student alone, consulted before the gate enforces, in every cycle they are a member of."
              domains={data.override_domains}
              permission={data.actions.grant_enrollment_override}
            />
            <GrantStudentTargetOverride
              data={data}
              enrollmentId={enrollmentId}
              target="cycle"
            />
            <GrantStudentTargetOverride
              data={data}
              enrollmentId={enrollmentId}
              target="job"
            />
          </>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Enrollment history</CardTitle>
          <span className="text-body-sm text-muted-foreground">
            {counted(data.enrollments.length, "record")}
          </span>
        </CardHeader>
        <CardBody className="max-w-md">
          <Field label="Enrollment" hint="Switching records never merges their applications or discipline.">
            {(field) => (
              <Select
                {...field}
                value={enrollmentId}
                onChange={(event) => navigate(`/staff/student/${event.target.value}`)}
              >
                {data.enrollments.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.roll_number ?? "No roll number"}
                    {item.is_current ? " — current" : " — historical"}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardBody>
          <SubjectOverrides overrides={data.overrides} empty />
        </CardBody>
      </Card>

      <Memberships data={data} />
      <Applications data={data} />
      <OfferHistory data={data} />
      <Discipline data={data} />
      <AuditTrail data={data} />
    </>
  );
}

function GrantStudentTargetOverride({
  data,
  enrollmentId,
  target,
}: {
  data: StudentRecordPayload;
  enrollmentId: string;
  target: "cycle" | "job";
}) {
  const targets = data.override_targets ?? {
    cycle_domains: [],
    job_domains: [],
    cycles: [],
    jobs: [],
  };
  const choices = target === "job" ? targets.jobs : targets.cycles;
  const domains =
    target === "job" ? targets.job_domains : targets.cycle_domains;
  const initial = choices[0];
  const initialDomain = (domains[0] ??
    "") as CommandInput<"create_override">["rule_domain"];
  const targetChoices: Choice[] = [
    {
      name: "target_id",
      label: target === "job" ? "Job" : "Cycle",
      kind: "select",
      required: true,
      initialValue: initial?.id ?? "",
      options: choices.map((item) => ({
        value: item.id,
        label:
          target === "job" && "cycle" in item
            ? `${item.cycle.name} — ${item.company_name} — ${item.title}`
            : "kind" in item
              ? `${item.name} — ${humanise(item.kind)}`
              : item.id,
      })),
      hint: `Only ${target}s in cycles you may administer are listed.`,
    },
    ...overrideChoices(domains),
  ];
  const firstCycleId =
    initial && target === "job" && "cycle" in initial ? initial.cycle.id : initial?.id ?? "";

  return (
    <PreviewConfirm
      command="create_override"
      input={{
        cycle_id: firstCycleId,
        ...(target === "job" ? { job_id: initial?.id ?? "" } : {}),
        enrollment_id: enrollmentId,
        rule_domain: initialDomain,
        allow: true,
        reason: "",
      }}
      title={`Grant a ${target}-and-student override?`}
      description={
        target === "job"
          ? `A pre-application exception for ${data.enrollment?.full_name ?? "this student"} on one job only.`
          : `An exception for ${data.enrollment?.full_name ?? "this student"} in one cycle only.`
      }
      confirmLabel="Grant"
      choices={targetChoices}
      transformInput={(input) => {
        const values = input as unknown as Record<string, unknown>;
        const selected = choices.find((item) => item.id === values.target_id);
        const wire = { ...values };
        delete wire.target_id;
        if (target === "job" && selected && "cycle" in selected) {
          return {
            ...wire,
            cycle_id: selected.cycle.id,
            job_id: selected.id,
            enrollment_id: enrollmentId,
          } as CommandInput<"create_override">;
        }
        return {
          ...wire,
          cycle_id: selected?.id ?? "",
          enrollment_id: enrollmentId,
        } as CommandInput<"create_override">;
      }}
      trigger={
        <Button variant="secondary" disabled={!initial || domains.length === 0}>
          Grant {target} override
        </Button>
      }
    />
  );
}

/**
 * The INT-1 correction: an administrator edits an admin-managed profile field.
 *
 * PRO-2's bulk upsert cannot stand in for this. It deliberately skips an empty
 * cell — which is what makes re-uploading the same roster idempotent — so it
 * can set a value and never clear one. Clearing is half the job here: a
 * mistyped CPI or a graduating year entered against the wrong student has to
 * be removable, and until it is the student's join checklist keeps passing on
 * a fact nobody stands behind.
 *
 * Every field is sent on every save, with the current value seeded, so the
 * dialog states the whole record rather than a diff of it — and the server's
 * summary names the fields that actually changed, which is what the preview
 * shows before anything is written.
 */
function EditProfile({
  data,
  enrollmentId,
}: {
  data: StudentRecordPayload;
  enrollmentId: string;
}) {
  const permission = data.actions.edit_profile;
  if (!permission.allowed) return null;
  const editable = data.profile.fields.filter((field) => field.admin_editable);
  const choices: Choice[] = editable.map((field) =>
    profileChoice(field.key, field.label, data),
  );
  return (
    <PreviewConfirm
      command="admin_update_profile"
      input={{ enrollment_id: enrollmentId, fields: {} }}
      title={`Edit ${data.enrollment?.full_name ?? "this"} profile?`}
      description="Admin-managed fields on this enrollment. Emptying a field clears it; the student may then supply it themselves until it holds a value again."
      confirmLabel="Save profile"
      choices={choices}
      transformInput={(input) => {
        const merged = input as unknown as Record<string, unknown>;
        const fields: Record<string, unknown> = {};
        for (const field of editable) {
          if (!(field.key in merged)) continue;
          const value = merged[field.key];
          // "" is how an emptied box arrives; the command spells a cleared
          // column `null`, and refuses the empty string for a number.
          fields[field.key] = value === "" ? null : value;
        }
        return { enrollment_id: enrollmentId, fields } as typeof input;
      }}
      renderSummary={(summary) => {
        // The generic panel would flatten `changed_fields` to its length, and
        // "1" is the one thing the operator already knows. Name them.
        const labels = new Map(data.profile.fields.map((f) => [f.key, f.label]));
        return summary.changed_fields.length === 0 ? (
          <p className="text-body-md text-muted-foreground">
            Nothing changes. Every field already holds this value.
          </p>
        ) : (
          <ul className="flex flex-col gap-gap-tight text-body-md text-foreground">
            {summary.changed_fields.map((key) => (
              <li key={key}>{labels.get(key) ?? key} changes</li>
            ))}
          </ul>
        );
      }}
      trigger={<Button variant="secondary">Edit profile</Button>}
    />
  );
}

const PROFILE_NUMBERS = new Set([
  "graduating_year",
  "cpi",
  "active_backlogs",
  "total_backlogs",
]);
const PROFILE_TAXONOMIES: Record<string, "programs" | "branches"> = {
  program_id: "programs",
  secondary_program_id: "programs",
  primary_branch_id: "branches",
  secondary_branch_id: "branches",
};
const BOOLEAN_OPTIONS = [
  { value: "true", label: "Yes" },
  { value: "false", label: "No" },
] as const;
const GENDER_OPTIONS = [
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "other", label: "Other" },
] as const;

/** One admin-managed field as the dialog renders it, seeded with what is true. */
function profileChoice(key: string, label: string, data: StudentRecordPayload): Choice {
  const live = data.profile.live[key];
  const initialValue = live === null || live === undefined ? "" : String(live);
  const taxonomy = PROFILE_TAXONOMIES[key];
  if (taxonomy) {
    return {
      name: key,
      label,
      kind: "select",
      initialValue,
      // Every branch is offered rather than only those the chosen program
      // admits: the pairing is a server rule, and a dialog that filtered by it
      // would be a second copy of that rule quietly disagreeing with the first.
      // An impossible pair is refused in the preview, by name.
      options: (data.profile.taxonomies[taxonomy] ?? []).map((item) => ({
        value: item.id,
        label: item.name,
      })),
    };
  }
  if (key === "is_dual_major" || key === "is_dual_degree") {
    return {
      name: key,
      label,
      kind: "select",
      initialValue: live === true ? "true" : "false",
      options: BOOLEAN_OPTIONS,
      coerce: "boolean",
    };
  }
  if (key === "gender") {
    return { name: key, label, kind: "select", initialValue, options: GENDER_OPTIONS };
  }
  if (key === "full_name") {
    // The one field with no empty state: PRO-1 seeds it from Google and the
    // command refuses to clear it.
    return { name: key, label, initialValue, required: true };
  }
  return {
    name: key,
    label,
    initialValue,
    ...(PROFILE_NUMBERS.has(key) ? { kind: "number" as const } : {}),
  };
}

function Memberships({ data }: { data: StudentRecordPayload }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cycle memberships</CardTitle>
        <span className="text-body-sm text-muted-foreground">{counted(data.memberships.length, "cycle")}</span>
      </CardHeader>
      <CardBody>
        {data.memberships.length === 0 ? (
          <EmptyState message="No cycle memberships belong to this enrollment." />
        ) : (
          <ul className="grid gap-gap-md sm:grid-cols-2">
            {data.memberships.map((item) => (
              <li key={item.id} className="rounded border border-border p-gap-lg">
                <div className="flex items-center justify-between gap-gap-md">
                  <p className="font-medium text-foreground">{item.cycle.name}</p>
                  <StatusChip domain="membership" value={item.status} />
                </div>
                <p className="mt-gap-tight text-body-sm text-muted-foreground">
                  {humanise(item.cycle.kind)}
                  {item.cycle.archived ? " · archived" : ""}
                  {item.auto_created ? " · created from an external attachment" : ""}
                </p>
                {item.decided_by || item.rejection_reason ? (
                  <p className="mt-gap-tight text-body-sm text-muted-foreground">
                    {item.decided_by ? `Decided by ${item.decided_by}` : ""}
                    {item.rejection_reason ? ` · ${item.rejection_reason}` : ""}
                  </p>
                ) : null}
                <div className="mt-gap-md flex flex-wrap items-center gap-gap-md">
                  <span className="text-body-sm text-muted-foreground">Outcome</span>
                  <OutcomeTag
                    cycleId={item.cycle.id}
                    membershipId={item.id}
                    subject={`this membership of ${item.cycle.name}`}
                    current={item.outcome_tag}
                    permission={item.actions.set_outcome_tag}
                  />
                  {/* The other screen that renders a membership row, and the
                      one an administrator reaches from a dispute rather than
                      from the queue. Same control, same server permission. */}
                  <MembershipExit
                    cycleId={item.cycle.id}
                    membershipId={item.id}
                    fullName={data.enrollment?.full_name ?? "this student"}
                    status={item.status}
                    actions={item.actions}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function Applications({ data }: { data: StudentRecordPayload }) {
  return (
    <section className="flex flex-col gap-gap-lg" aria-labelledby="applications-heading">
      <div>
        <h2 id="applications-heading" className="text-headline-lg text-foreground">
          Applications
        </h2>
        <p className="mt-gap-tight text-body-sm text-muted-foreground">
          Saved profile, round ledger and the full event timeline for every application.
        </p>
      </div>
      {data.applications.length === 0 ? (
        <EmptyState message="No applications belong to this enrollment." />
      ) : (
        data.applications.map((application) => (
          <ApplicationCard key={application.id} application={application} />
        ))
      )}
    </section>
  );
}

type Application = StudentRecordPayload["applications"][number];

function ApplicationCard({ application }: { application: Application }) {
  const changed = application.snapshot_diff.filter((row) => row.state !== "unchanged");
  // A card with a heading is a region, and naming it by that heading is what
  // lets a screen reader — and a test — address one application out of eight
  // rather than the page they all sit on.
  const titleId = `application-${application.id}-title`;
  return (
    <Card role="region" aria-labelledby={titleId}>
      <CardHeader>
        <div>
          <CardTitle id={titleId}>{application.job_title}</CardTitle>
          <p className="mt-gap-tight text-body-sm text-muted-foreground">
            {application.company_name} · {application.cycle.name}
            {application.current_round ? ` · ${application.current_round.name}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-gap-md">
          <StatusChip domain="application" value={application.status} />
          <GrantOverride
            scope={{
              cycle_id: application.cycle.id,
              application_id: application.id,
            }}
            title={`Grant an override for ${application.job_title}?`}
            description="A standing exception for this application alone. Eligibility and the application deadline have already been decided and are therefore unavailable here."
            domains={application.override_domains}
            permission={application.actions.grant_override}
            label="Grant application override"
          />
          <Reinstate application={application} />
          <ForceTransition application={application} />
        </div>
      </CardHeader>
      <CardBody className="flex flex-col gap-section-margin">
        <SubjectOverrides overrides={application.overrides} />
        <div>
          <h3 className="text-label-caps uppercase text-muted-foreground">Round ledger</h3>
          {application.round_states.length === 0 ? (
            <EmptyState message="No round state has been recorded for this application." />
          ) : (
            <ul className="mt-gap-md grid gap-gap-md sm:grid-cols-2 lg:grid-cols-3">
              {application.round_states.map((round) => (
                <li key={round.round_id} className="rounded border border-border p-gap-md">
                  <p className="font-medium text-foreground">
                    {round.ord}. {round.round_name}
                  </p>
                  <div className="mt-gap-tight flex flex-wrap gap-gap-md">
                    <StatusChip domain="round" value={round.result} />
                    <StatusChip domain="attendance" value={round.attendance} />
                  </div>
                  {round.venue_override || round.scheduled_at_override ? (
                    <p className="mt-gap-tight text-body-sm text-muted-foreground">
                      {round.venue_override ?? "Venue unchanged"}
                      {round.scheduled_at_override ? ` · ${formatZonedDateTime(round.scheduled_at_override)}` : ""}
                    </p>
                  ) : null}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div>
          <h3 className="text-label-caps uppercase text-muted-foreground">Snapshot versus live profile</h3>
          <p className="mt-gap-tight text-body-sm text-muted-foreground">
            {changed.length === 0
              ? "The profile still matches what this application was judged on."
              : `${changed.length} field${changed.length === 1 ? "" : "s"} changed or absent since submission.`}
          </p>
          <DataTable
            className="mt-gap-md"
            columns={snapshotColumns}
            rows={application.snapshot_diff}
            rowKey={(row) => row.key}
          />
        </div>

        <div>
          <h3 className="text-label-caps uppercase text-muted-foreground">Application timeline</h3>
          <Timeline events={application.events} />
        </div>
      </CardBody>
    </Card>
  );
}

const snapshotColumns: Column<Application["snapshot_diff"][number]>[] = [
  {
    key: "field",
    header: "Field",
    cell: (row) => (
      <span>
        <span className="block font-medium">{row.label}</span>
        <span className="block text-body-sm text-muted-foreground">Owned by {humanise(row.owner)}</span>
      </span>
    ),
  },
  { key: "snapshot", header: "At submission", cell: (row) => renderValue(row.snapshot) },
  { key: "live", header: "Live now", cell: (row) => renderValue(row.live) },
  {
    key: "state",
    header: "Comparison",
    cell: (row) => (
      <span className={row.state === "changed" ? "font-semibold text-warning" : "text-muted-foreground"}>
        {humanise(row.state)}
      </span>
    ),
  },
];

function Reinstate({ application }: { application: Application }) {
  const permission = application.actions.reinstate;
  const choices: Choice[] = [];
  if (application.rounds.length > 0) {
    choices.push({
      name: "target_round_id",
      label: "Return to round",
      kind: "select",
      required: true,
      options: application.rounds.map((round) => ({ value: round.id, label: `${round.ord}. ${round.name}` })),
      hint: "The preview lists every round-state row it keeps and clears.",
    });
  }
  choices.push(
    { name: "reason", label: "Reason", kind: "textarea", required: true },
    {
      name: "notify",
      label: "Student notification",
      kind: "select",
      options: [
        { value: "true", label: "Notify the student" },
        { value: "false", label: "Do not notify" },
      ],
      coerce: "boolean",
      hint: "Notification is on by default. Select only to change that choice.",
    },
  );
  return (
    <PreviewConfirm
      command="reinstate_application"
      input={{
        cycle_id: application.cycle.id,
        application_id: application.id,
        target_round_id: null,
        expected_status: application.status as ApplicationStatus,
        reason: "",
        notify: true,
      }}
      title={`Reinstate ${application.job_title}?`}
      description="Return the application to a chosen pipeline position and repair its round-state ledger."
      confirmLabel="Reinstate"
      renderSummary={(summary) => (
        <ReinstatementPlan summary={summary as unknown as Record<string, unknown>} />
      )}
      choices={choices}
      trigger={
        <Button variant="secondary" disabled={!permission.allowed} title={permission.human ?? undefined}>
          Reinstate
        </Button>
      }
    />
  );
}


function ForceTransition({ application }: { application: Application }) {
  const permission = application.actions.force_transition;
  return (
    <PreviewConfirm
      command="force_transition"
      input={{
        cycle_id: application.cycle.id,
        application_id: application.id,
        expected_status: application.status as ApplicationStatus,
        to_status: "in_progress",
        reason: "",
      }}
      title={`Force a transition for ${application.job_title}?`}
      description="This changes only the stored status and event. Read the preview's unperformed-consequences sentence before confirming."
      confirmLabel="Force transition"
      destructive
      choices={[
        {
          name: "to_status",
          label: "Destination status",
          kind: "select",
          required: true,
          options: APPLICATION_STATUSES.filter((status) => status !== application.status).map((status) => ({
            value: status,
            label: humanise(status),
          })),
        },
        { name: "reason", label: "Reason", kind: "textarea", required: true },
      ]}
      trigger={
        <Button variant="ghost" disabled={!permission.allowed} title={permission.human ?? undefined}>
          Force transition
        </Button>
      }
    />
  );
}

function Timeline({ events }: { events: TimelineEvent[] }) {
  if (events.length === 0) {
    return <EmptyState message="No events were recorded." />;
  }
  return (
    <ol className="mt-gap-md flex flex-col gap-gap-md border-l-2 border-border pl-gap-lg">
      {events.map((event) => (
        <li key={event.id}>
          <div className="flex flex-wrap items-center gap-gap-md">
            <p className="font-medium text-foreground">{humanise(event.event_type)}</p>
            {event.to_status ? <StatusChip domain="application" value={event.to_status} /> : null}
          </div>
          <p className="mt-gap-tight text-body-sm text-muted-foreground">
            {event.created_at ? formatDateTime(event.created_at) : "Time unavailable"} · {event.actor ?? "System"}
            {event.actor_role ? ` (${humanise(event.actor_role)})` : ""}
            {event.from_round || event.to_round ? ` · ${event.from_round ?? "—"} → ${event.to_round ?? "—"}` : ""}
          </p>
          {event.reason ? <p className="mt-gap-tight text-body-sm text-foreground">{event.reason}</p> : null}
          <EventPayload payload={event.payload} labels={event.payload_labels} />
        </li>
      ))}
    </ol>
  );
}

function OfferHistory({ data }: { data: StudentRecordPayload }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Offer history</CardTitle>
        <span className="text-body-sm text-muted-foreground">
          {counted(data.offers.length, "portal offer")} ·{" "}
          {counted(data.external_offers.length, "external offer")}
        </span>
      </CardHeader>
      <CardBody className="grid gap-section-margin lg:grid-cols-2">
        <div>
          <h3 className="text-label-caps uppercase text-muted-foreground">Portal offers</h3>
          {data.offers.length === 0 ? (
            <EmptyState message="No portal offers." />
          ) : (
            <ul className="mt-gap-md flex flex-col gap-gap-md">
              {data.offers.map((offer) => (
                <li key={offer.id} className="rounded border border-border p-gap-lg">
                  <div className="flex flex-wrap items-center justify-between gap-gap-md">
                    <p className="font-medium text-foreground">{offer.job_title} · {offer.company_name}</p>
                    <StatusChip
                      domain="application"
                      value={offer.response ?? (offer.terminated_at ? "offer_terminated" : "offered")}
                    />
                  </div>
                  {offer.deadline_at ? (
                    <p className="mt-gap-tight text-body-sm text-muted-foreground">
                      Deadline {formatDateTime(offer.deadline_at)}
                    </p>
                  ) : null}
                  {offer.termination_reason ? <p className="mt-gap-tight text-body-sm">{offer.termination_reason}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div>
          <h3 className="text-label-caps uppercase text-muted-foreground">External offers</h3>
          {data.external_offers.length === 0 ? (
            <EmptyState message="No external offers." />
          ) : (
            <ul className="mt-gap-md flex flex-col gap-gap-md">
              {data.external_offers.map((offer) => (
                <li key={offer.id} className="rounded border border-border p-gap-lg">
                  <div className="flex items-center justify-between gap-gap-md">
                    <p className="font-medium text-foreground">{offer.company_name}</p>
                    <StatusChip domain="external" value={offer.status} />
                  </div>
                  <p className="mt-gap-tight text-body-sm text-muted-foreground">
                    {humanise(offer.source)} · {humanise(offer.outcome)}
                    {offer.attached_cycle_name ? ` · attached to ${offer.attached_cycle_name}` : " · unattached"}
                  </p>
                  {offer.notes ? <p className="mt-gap-tight text-body-sm">{offer.notes}</p> : null}
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function Discipline({ data }: { data: StudentRecordPayload }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Discipline</CardTitle>
        <span className="text-body-sm text-muted-foreground">
          {counted(data.discipline.strikes.length, "strike")} ·{" "}
          {counted(data.discipline.penalties.length, "penalty", "penalties")}
        </span>
      </CardHeader>
      <CardBody className="grid gap-section-margin lg:grid-cols-2">
        <HistoryList
          title="Strikes"
          empty="No strikes."
          rows={data.discipline.strikes.map((strike) => ({
            id: strike.id,
            title: strike.reason,
            detail: strike.is_active
              ? `Active · ${humanise(strike.source)}`
              : `Revoked by ${strike.revocation?.actor ?? "unknown"}${strike.revocation?.at ? ` · ${formatDateTime(strike.revocation.at)}` : ""} · source: ${strike.revocation?.source ?? "audit_log"}`,
          }))}
        />
        <HistoryList
          title="Penalties"
          empty="No penalties."
          rows={data.discipline.penalties.map((penalty) => ({
            id: penalty.id,
            title: penalty.reasons,
            detail: penalty.is_active
              ? penalty.from_strikes ? "Active · converted from strikes" : "Active · direct"
              : `Revoked by ${penalty.revoked_by ?? "unknown"}${penalty.revoked_at ? ` · ${formatDateTime(penalty.revoked_at)}` : ""}`,
          }))}
        />
      </CardBody>
    </Card>
  );
}

function HistoryList({ title, empty, rows }: { title: string; empty: string; rows: { id: string; title: string; detail: string }[] }) {
  return (
    <div>
      <h3 className="text-label-caps uppercase text-muted-foreground">{title}</h3>
      {rows.length === 0 ? <EmptyState message={empty} /> : (
        <ul className="mt-gap-md flex flex-col gap-gap-md">
          {rows.map((row) => (
            <li key={row.id} className="rounded border border-border p-gap-lg">
              <p className="font-medium text-foreground">{row.title}</p>
              <p className="mt-gap-tight text-body-sm text-muted-foreground">{row.detail}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AuditTrail({ data }: { data: StudentRecordPayload }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Enrollment audit trail</CardTitle>
        <span className="text-body-sm text-muted-foreground">{counted(data.audit.length, "row")}</span>
      </CardHeader>
      <CardBody>
        <p className="mb-gap-lg text-body-sm text-muted-foreground">
          Includes external-offer writes that have no application event, and strike revocations whose actor exists only here.
        </p>
        {data.audit.length === 0 ? <EmptyState message="No audit rows." /> : (
          <ol className="flex flex-col gap-gap-md">
            {data.audit.map((row) => (
              <li key={row.id} className="rounded border border-border p-gap-md">
                <p className="font-medium text-foreground">{humanise(row.action)}</p>
                <p className="mt-gap-tight text-body-sm text-muted-foreground">
                  {row.created_at ? formatDateTime(row.created_at) : "Time unavailable"} · {row.actor ?? "System"}
                  {row.subject_type ? ` · ${humanise(row.subject_type)}` : ""}
                </p>
                <AuditDetails
                  action={row.action}
                  details={row.details}
                  fields={data.profile.fields}
                />
              </li>
            ))}
          </ol>
        )}
      </CardBody>
    </Card>
  );
}

function AuditDetails({
  action,
  details,
  fields,
}: {
  action: string;
  details: Record<string, unknown>;
  fields: StudentRecordPayload["profile"]["fields"];
}) {
  const labels = new Map(fields.map((field) => [field.key, field.label]));
  const before = record(details.before);
  const after = record(details.after);
  const directField = action === "profile_field_change" && typeof details.field === "string"
    ? details.field
    : null;
  const changedKeys = directField
    ? [directField]
    : [...new Set([...Object.keys(before ?? {}), ...Object.keys(after ?? {})])];
  const remaining = Object.entries(details).filter(
    ([key]) => !["before", "after"].includes(key) && !(directField && key === "field"),
  );

  if (changedKeys.length === 0 && remaining.length === 0) return null;

  return (
    <div className="mt-gap-tight text-body-sm">
      {changedKeys.length > 0 ? (
        <ul aria-label="Field changes" className="flex flex-col gap-gap-tight text-foreground">
          {changedKeys.map((key) => (
            <li key={key}>
              <span className="font-medium">{labels.get(key) ?? humanise(key)}:</span>{" "}
              {formatAuditValue(before ? before[key] : details.before)} →{" "}
              {formatAuditValue(after ? after[key] : details.after)}
            </li>
          ))}
        </ul>
      ) : null}
      {remaining.length > 0 ? (
        <details className="mt-gap-tight text-muted-foreground">
          <summary className="cursor-pointer">Details ({remaining.length})</summary>
          <dl className="mt-gap-tight grid gap-x-gap-lg gap-y-gap-tight sm:grid-cols-[max-content_1fr]">
            {remaining.map(([key, value]) => (
              <div key={key} className="contents">
                <dt className="font-medium text-foreground">{humanise(key)}</dt>
                <dd className="break-all">{formatAuditValue(value, key)}</dd>
              </div>
            ))}
          </dl>
        </details>
      ) : null}
    </div>
  );
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

const ENUM_DETAIL_KEYS = new Set([
  "action",
  "from_status",
  "kind",
  "operation",
  "outcome",
  "role",
  "source",
  "status",
  "subject_type",
  "to_status",
]);

function formatAuditValue(value: unknown, key?: string): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) {
    return value.length === 0
      ? "None"
      : value.map((nested) => formatAuditValue(nested, key)).join(", ");
  }
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([nestedKey, nested]) => `${humanise(nestedKey)}: ${formatAuditValue(nested, nestedKey)}`)
      .join("; ");
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return typeof value === "string" && key && ENUM_DETAIL_KEYS.has(key)
    ? humanise(value)
    : String(value);
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length === 0 ? "—" : value.map(renderValue).join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}
