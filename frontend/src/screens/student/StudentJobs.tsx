import { Briefcase, CheckCircle2, Lock } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { payload, type StudentJobsPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardBody } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDate } from "@/lib/date";

type Job = StudentJobsPayload["jobs"][number];

/**
 * Every published job in a cycle, each with its full verdict (Behavior JOB-4).
 *
 * A job the student cannot apply to is shown, not hidden — with every reason,
 * because ELG-3 evaluates the gates and the rule both and a student told only
 * the first would fix it, come back, and discover the second.
 */
export function StudentJobs() {
  const { id = "" } = useParams();
  const screen = useScreen("cycle/{id}/jobs", { params: { id } });

  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<StudentJobsPayload>(screen.data);

  return (
    <>
      <PageHeader
        title={data.cycle.name}
        subtitle={
          data.jobs.length === 0
            ? "No jobs have been published in this cycle yet."
            : `${data.eligible_count} of ${data.jobs.length} open to you.`
        }
        actions={<StatusChip domain="membership" value={data.membership_status} />}
      />

      {data.membership_status !== "active" ? (
        <div className="rounded border border-warning-border bg-warning-subtle p-container-padding">
          <p className="text-body-md font-semibold text-warning">
            Your membership is not active
          </p>
          <p className="mt-gap-tight text-body-md text-foreground">
            You can read every job here, but you cannot apply until a coordinator approves
            your membership.
          </p>
        </div>
      ) : null}

      {data.jobs.length === 0 ? (
        <Card>
          <CardBody>
            <EmptyState
              icon={<Briefcase className="h-8 w-8" />}
              message="Nothing published yet. Jobs appear here as soon as the office publishes them."
            />
          </CardBody>
        </Card>
      ) : (
        <ul className="flex flex-col gap-gap-lg">
          {data.jobs.map((job) => (
            <li key={job.id}>
              <JobCard job={job} />
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function JobCard({ job }: { job: Job }) {
  return (
    <Card>
      <CardBody className="flex flex-col gap-gap-lg">
        <div className="flex flex-wrap items-start justify-between gap-gap-lg">
          <div className="min-w-0">
            <Link
              to={`/jobs/${job.id}`}
              className="text-headline-md text-accent hover:underline"
            >
              {job.title}
            </Link>
            <p className="text-body-md text-muted-foreground">
              {job.company.name}
              {job.location ? ` · ${job.location}` : ""}
              {job.sector ? ` · ${job.sector}` : ""}
            </p>
          </div>
          <div className="flex flex-col items-end gap-gap-tight">
            {job.ctc_lpa ? (
              <span className="tabular text-headline-md text-foreground">
                ₹{job.ctc_lpa} LPA
              </span>
            ) : job.stipend_month ? (
              <span className="tabular text-headline-md text-foreground">
                ₹{job.stipend_month}/month
              </span>
            ) : null}
            {job.application_deadline ? (
              <span className="text-body-sm text-muted-foreground">
                Closes {formatDate(job.application_deadline)}
              </span>
            ) : null}
          </div>
        </div>

        {job.application ? (
          <div className="flex items-center gap-gap-md">
            <span className="text-body-md text-muted-foreground">Your application:</span>
            <StatusChip domain="application" value={job.application.status} />
          </div>
        ) : job.eligible ? (
          <p className="flex items-center gap-gap-md text-body-md text-success">
            <CheckCircle2 aria-hidden className="h-4 w-4" />
            You meet every requirement for this job.
          </p>
        ) : (
          <Reasons reasons={job.reasons} />
        )}
      </CardBody>
    </Card>
  );
}

export function Reasons({
  reasons,
}: {
  reasons: { code: string; human: string }[];
}) {
  if (reasons.length === 0) {
    return (
      <p className="text-body-sm text-muted-foreground">
        Apply is unavailable, but no additional reason was supplied. Refresh the page or contact the placement office.
      </p>
    );
  }
  return (
    <div className="rounded border border-border bg-muted p-gap-lg">
      <p className="flex items-center gap-gap-md text-body-md font-semibold text-foreground">
        <Lock aria-hidden className="h-4 w-4 text-muted-foreground" />
        Why you cannot apply
      </p>
      <ul className="mt-gap-md flex list-disc flex-col gap-gap-tight pl-gap-lg">
        {reasons.map((reason, index) => (
          <li key={index} className="text-body-md text-muted-foreground">
            {reason.human}
          </li>
        ))}
      </ul>
    </div>
  );
}
