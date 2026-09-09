import { CalendarRange } from "lucide-react";
import { Link } from "react-router-dom";

import type { StudentCyclesPayload } from "@/api/payloads";
import { MembershipExitPlan } from "@/components/CommandSummaryDetails";
import { PreviewConfirm, type Choice } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/statusChip";
import { humanise } from "@/lib/text";
import { EmptyState } from "@/components/ui/states";
import { formatDate } from "@/lib/date";
import { reasonText } from "@/lib/reasons";

type Cycle = StudentCyclesPayload["cycles"][number];
type Resume = StudentCyclesPayload["resumes"][number];

export function StudentCycleSections({
  cycles,
  enrollmentId,
  resumes,
}: {
  cycles: Cycle[];
  enrollmentId: string;
  resumes: Resume[];
}) {
  const yourCycles = cycles.filter((cycle) => cycle.membership?.status === "active");
  const otherCycles = cycles.filter((cycle) => cycle.membership?.status !== "active");

  return (
    <>
      <CycleSection
        id="your-cycles"
        title="Your cycles"
        cycles={yourCycles}
        enrollmentId={enrollmentId}
        resumes={resumes}
        emptyMessage="You are not an active member of any cycle right now."
      />
      <CycleSection
        id="other-cycles"
        title="Other cycles"
        cycles={otherCycles}
        enrollmentId={enrollmentId}
        resumes={resumes}
        emptyMessage="There are no other cycles available to you right now."
      />
    </>
  );
}

function CycleSection({
  id,
  title,
  cycles,
  enrollmentId,
  resumes,
  emptyMessage,
}: {
  id: string;
  title: string;
  cycles: Cycle[];
  enrollmentId: string;
  resumes: Resume[];
  emptyMessage: string;
}) {
  const headingId = `${id}-heading`;

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-gap-lg">
      <h2 id={headingId} className="text-headline-lg text-foreground">
        {title}
      </h2>
      {cycles.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon={<CalendarRange className="h-8 w-8" />}
              message={emptyMessage}
            />
          </CardBody>
        </Card>
      ) : (
        <div className="grid gap-gap-lg sm:grid-cols-2 lg:grid-cols-3">
          {cycles.map((cycle) => (
            <CycleCard
              key={cycle.id}
              cycle={cycle}
              enrollmentId={enrollmentId}
              resumes={resumes}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function CycleCard({
  cycle,
  enrollmentId,
  resumes,
}: {
  cycle: Cycle;
  enrollmentId: string;
  resumes: Resume[];
}) {
  const isActiveMember = cycle.membership?.status === "active";

  return (
    <Card>
      <CardBody className="flex flex-col gap-gap-md">
        <div className="flex items-start justify-between gap-gap-md">
          <h3 className="text-headline-md">
            {isActiveMember ? (
              <Link to={`/cycles/${cycle.id}/jobs`} className="text-accent hover:underline">
                {cycle.name}
              </Link>
            ) : (
              cycle.name
            )}
          </h3>
          {cycle.membership ? (
            <StatusChip domain="membership" value={cycle.membership.status} />
          ) : null}
        </div>
        <p className="text-body-sm text-muted-foreground">{humanise(cycle.kind)}</p>
        {cycle.description ? (
          <p className="text-body-md text-foreground">{cycle.description}</p>
        ) : null}
        {cycle.membership?.rejection_reason ? (
          <p className="text-body-sm text-danger">
            Reason: {cycle.membership.rejection_reason}
          </p>
        ) : null}
        {!cycle.membership && cycle.can_join ? (
          <p className="text-body-sm text-success">
            Eligible to join{cycle.requires_approval ? " with coordinator approval" : ""}.
          </p>
        ) : null}
        {cycle.reasons.length > 0 ? (
          <ul className="list-disc space-y-gap-tight pl-container-padding text-body-sm text-muted-foreground">
            {cycle.reasons.map((reason, index) => (
              <li key={`${reason.code}:${reason.path ?? ""}:${index}`}>
                {reasonText(reason.code, reason.human)}
              </li>
            ))}
          </ul>
        ) : null}
        {cycle.registration_closes_at ? (
          <p className="text-body-sm text-muted-foreground">
            Registration closes {formatDate(cycle.registration_closes_at)}
          </p>
        ) : null}
        <CycleActions cycle={cycle} enrollmentId={enrollmentId} resumes={resumes} />
      </CardBody>
    </Card>
  );
}

/** What CYC-3 asks of anyone entering a cycle, first time or not. */
const JOIN_CHOICES = (resumes: Resume[]): Choice[] => [
  {
    name: "default_resume_id",
    label: "Resume for this cycle",
    kind: "select",
    required: true,
    options: resumes.map((resume) => ({ value: resume.id, label: resume.label })),
  },
  {
    name: "consent",
    label: "Consent",
    kind: "select",
    required: true,
    coerce: "boolean",
    options: [{ value: "true", label: "I consent to sharing my application data" }],
  },
];

function CycleActions({
  cycle,
  enrollmentId,
  resumes,
}: {
  cycle: Cycle;
  enrollmentId: string;
  resumes: Resume[];
}) {
  if (!cycle.membership && cycle.can_join) {
    return (
      <PreviewConfirm
        command="join_cycle"
        input={{
          cycle_id: cycle.id,
          enrollment_id: enrollmentId,
          default_resume_id: "",
          consent: false,
        }}
        title={`Join ${cycle.name}?`}
        confirmLabel={cycle.requires_approval ? "Request to join" : "Join cycle"}
        choices={JOIN_CHOICES(resumes)}
        trigger={<Button>{cycle.requires_approval ? "Request to join" : "Join"}</Button>}
      />
    );
  }
  // A member who was rejected, and a member who left of their own accord, take
  // the same way back in: re-entry re-runs every join check and honours the
  // cycle's approval setting (the design review §4.34), so it asks for the consent and
  // the resume a first join asks for.
  const returning = cycle.membership?.status;
  if (returning === "rejected" || returning === "withdrawn") {
    const rejected = returning === "rejected";
    return (
      <PreviewConfirm
        command="rerequest_membership"
        input={{
          cycle_id: cycle.id,
          enrollment_id: enrollmentId,
          default_resume_id: "",
          consent: false,
        }}
        title={rejected ? `Request ${cycle.name} again?` : `Register for ${cycle.name} again?`}
        description="Your profile, resume, the registration window and the join rule are all checked again."
        confirmLabel={
          cycle.requires_approval ? "Request again" : "Register again"
        }
        choices={JOIN_CHOICES(resumes)}
        trigger={
          <Button variant="secondary">
            {rejected ? "Request again" : "Register again"}
          </Button>
        }
      />
    );
  }
  // CYC-3 lets a pending member cancel their own request; without a control
  // for it, someone who applied to the wrong cycle has to ask staff for a
  // rejection they did not earn.
  if (returning === "active" || returning === "pending") {
    const active = returning === "active";
    return (
      <PreviewConfirm
        command="withdraw_membership"
        input={{ cycle_id: cycle.id, enrollment_id: enrollmentId }}
        title={
          active
            ? `Withdraw from ${cycle.name}?`
            : `Cancel your request to join ${cycle.name}?`
        }
        description={
          active
            ? "The preview lists every live application this membership exit will auto-withdraw."
            : "Your request is cancelled. You can register again while the window is open."
        }
        confirmLabel={active ? "Withdraw from cycle" : "Cancel request"}
        destructive
        renderSummary={(summary) => (
          <MembershipExitPlan summary={summary as unknown as Record<string, unknown>} />
        )}
        trigger={
          <Button variant="destructive-ghost">
            {active ? "Withdraw" : "Cancel request"}
          </Button>
        }
      />
    );
  }
  return null;
}
