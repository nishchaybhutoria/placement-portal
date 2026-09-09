import { Building2, CalendarClock, FileText, Layers } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { payload, type MeApplicationsPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { EditApplicationForm } from "@/components/ApplicationForm";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDate } from "@/lib/date";
import { humanise } from "@/lib/text";

type Application = MeApplicationsPayload["applications"][number];

/**
 * Everything this student has applied to (Behavior APP-3).
 *
 * The withdraw button appears exactly when the server would allow it: the
 * screen reports `can_withdraw`, computed from the same window evaluator the
 * command enforces, rather than the client re-deriving it from a deadline.
 * Two cycle policy flags and any per-application override feed that answer, so
 * a client that guessed would offer buttons the server refuses.
 */
export function MyApplications() {
  const screen = useScreen("me/applications");

  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<MeApplicationsPayload>(screen.data);

  return (
    <>
      <PageHeader
        title="My applications"
        subtitle={
          data.counts.total === 0
            ? "You have not applied to anything yet."
            : `${data.counts.in_progress} in progress of ${data.counts.total} total.`
        }
      />

      {data.applications.length === 0 ? (
        <EmptyState message="Open a cycle you are a member of and apply to a published job." />
      ) : (
        <div className="flex flex-col gap-gap-lg">
          {data.applications.map((application) => (
            <ApplicationCard
              key={application.id}
              application={application}
              enrollmentId={data.enrollment_id}
              resumes={data.resumes}
            />
          ))}
        </div>
      )}
    </>
  );
}

function ApplicationCard({
  application,
  enrollmentId,
  resumes,
}: {
  application: Application;
  enrollmentId: string;
  resumes: MeApplicationsPayload["resumes"];
}) {
  const { job, cycle, round } = application;
  const [editing, setEditing] = useState(false);

  return (
    <Card>
      <CardBody className="flex flex-col gap-gap-lg">
        <div className="flex flex-wrap items-start justify-between gap-gap-md">
          <div className="min-w-0">
            <Link
              to={`/jobs/${job.id}`}
              className="text-headline-md text-foreground hover:text-brand"
            >
              {job.title}
            </Link>
            <p className="mt-gap-tight flex flex-wrap items-center gap-gap-md text-body-sm text-muted-foreground">
              <span className="flex items-center gap-gap-tight">
                <Building2 aria-hidden className="h-3.5 w-3.5" />
                {job.company}
              </span>
              <span className="flex items-center gap-gap-tight">
                <Layers aria-hidden className="h-3.5 w-3.5" />
                {cycle.name}
              </span>
              {job.application_deadline ? (
                <span className="flex items-center gap-gap-tight">
                  <CalendarClock aria-hidden className="h-3.5 w-3.5" />
                  Closes {formatDate(job.application_deadline)}
                </span>
              ) : null}
            </p>
          </div>
          <StatusChip domain="application" value={application.status} />
        </div>

        <div className="flex flex-wrap items-center gap-gap-lg text-body-sm text-muted-foreground">
          {/* An open-cycle application holds no position at all (JOB-6), which
              is a different thing from being at round one. */}
          <span>
            {round ? `Round ${round.ord} of ${round.of} — ${round.name}` : "No rounds"}
          </span>
          <span>Applied {formatDate(application.applied_at)}</span>
          <a
            href={application.resume_url}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-gap-tight text-brand hover:underline"
          >
            <FileText aria-hidden className="h-3.5 w-3.5" />
            Resume
          </a>
          {application.answer_count > 0 ? (
            <span>
              {application.answer_count} answer
              {application.answer_count === 1 ? "" : "s"}
            </span>
          ) : null}
        </div>

        {application.window_reasons.length > 0 ? (
          <p className="text-body-sm text-muted-foreground">
            {application.window_reasons.map((reason) => reason.human).join(" ")}
          </p>
        ) : null}

        <div className="flex items-center gap-gap-md">
          {application.can_edit ? (
            <Button variant="secondary" size="sm" onClick={() => setEditing((open) => !open)}>
              Edit
            </Button>
          ) : null}
          {application.can_withdraw ? (
            <PreviewConfirm
              command="withdraw_application"
              input={{
                cycle_id: cycle.id,
                enrollment_id: enrollmentId,
                application_id: application.id,
              }}
              title={`Withdraw from ${job.title}?`}
              description="You keep your place in the cycle. Applying again later is allowed while the deadline stands, but nothing is held for you."
              confirmLabel="Withdraw"
              destructive
              trigger={
                <Button variant="ghost" size="sm">
                  Withdraw
                </Button>
              }
            />
          ) : null}
          <Timeline application={application} />
        </div>

        {editing ? (
          <div className="border-t border-border pt-gap-lg">
            <EditApplicationForm
              cycleId={cycle.id}
              enrollmentId={enrollmentId}
              applicationId={application.id}
              questions={application.edit_form.questions}
              answers={application.edit_form.answers}
              resumes={resumes}
              resumeUrl={application.resume_url}
              onDone={() => setEditing(false)}
            />
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

function Timeline({ application }: { application: Application }) {
  if (application.timeline.length === 0) return null;
  return (
    <details className="text-body-sm">
      <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
        History ({application.timeline.length})
      </summary>
      <ol className="mt-gap-md flex flex-col gap-gap-tight border-l border-border pl-gap-lg">
        {application.timeline.map((event, index) => (
          <li key={`${event.event_type}-${index}`} className="flex flex-wrap items-center gap-gap-md text-muted-foreground">
            <span className="text-foreground">{humanise(event.event_type)}</span>
            {event.to_status ? <StatusChip domain="application" value={event.to_status} /> : null}
            {event.at ? <span>{formatDate(event.at)}</span> : null}
            {event.reason ? <span>{event.reason}</span> : null}
          </li>
        ))}
      </ol>
    </details>
  );
}
