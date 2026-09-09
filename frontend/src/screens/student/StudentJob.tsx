import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { useRef } from "react";
import { Link, useParams } from "react-router-dom";

import { payload, type StudentJobPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { ApplyApplicationForm } from "@/components/ApplicationForm";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDateTime, formatZonedDateTime } from "@/lib/date";
import { Reasons } from "./StudentJobs";

/** One job in full, including the APP-1 form generated from its schema. */
export function StudentJob() {
  const { id = "" } = useParams();
  const screen = useScreen("job/{id}", { params: { id } });
  const form = useRef<HTMLDivElement>(null);

  /**
   * Take the reader to the form and put the cursor in it.
   *
   * This was `<a href="#application-form">`, which is dead on the second click
   * — the hash is already current, so the browser does not scroll again — and
   * on mobile landed under the sticky header. The submit stays where it is:
   * one Apply button that applies, and one that takes you to it, rather than
   * two paths through APP-1's validation.
   */
  function goToForm() {
    form.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    form.current?.querySelector<HTMLElement>(
      "input, select, textarea, button",
    )?.focus({ preventScroll: true });
  }

  if (screen.isPending) return <ScreenSkeleton variant="detail" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<StudentJobPayload>(screen.data);
  const { job, compensation, eligibility } = data;

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link
            to={`/cycles/${data.cycle.id}/jobs`}
            className="inline-flex items-center gap-gap-tight hover:underline"
          >
            <ArrowLeft className="h-3 w-3" /> {data.cycle.name}
          </Link>
        }
        title={job.title}
        subtitle={`${job.company.name}${job.location ? ` · ${job.location}` : ""}`}
        actions={
          data.application ? (
            <StatusChip domain="application" value={data.application.status} />
          ) : eligibility.eligible ? (
            <Button variant="primary" onClick={goToForm}>
              Apply
            </Button>
          ) : (
            <Button variant="primary" disabled title={eligibility.reasons[0]?.human}>
              Apply
            </Button>
          )
        }
      />

      <div className="grid gap-section-margin lg:grid-cols-[2fr_1fr]">
        <div className="flex flex-col gap-section-margin">
          <Card>
            <CardHeader>
              <CardTitle>About this role</CardTitle>
            </CardHeader>
            <CardBody>
              <p className="whitespace-pre-wrap text-body-md text-foreground">
                {job.description ?? "No description provided."}
              </p>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Selection process</CardTitle>
            </CardHeader>
            <CardBody>
              {data.rounds.length === 0 ? (
                <EmptyState message="This role has no scheduled rounds." />
              ) : (
                <ol className="flex flex-col gap-gap-lg">
                  {data.rounds.map((round, index) => (
                    <li key={round.round_id} className="flex gap-gap-lg">
                      <span className="tabular flex h-7 w-7 shrink-0 items-center justify-center rounded-sm bg-muted text-body-sm font-semibold text-muted-foreground">
                        {index + 1}
                      </span>
                      <div className="min-w-0">
                        <p className="text-body-md font-medium text-foreground">
                          {round.name}
                        </p>
                        <p className="text-body-sm text-muted-foreground">
                          {[
                            round.round_type,
                            round.venue,
                            round.duration_min ? `${round.duration_min} min` : null,
                            round.scheduled_at
                              ? formatZonedDateTime(round.scheduled_at)
                              : null,
                          ]
                            .filter(Boolean)
                            .join(" · ")}
                        </p>
                        {round.instructions ? (
                          <p className="mt-gap-tight text-body-sm text-foreground">
                            {round.instructions}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Application form</CardTitle>
            </CardHeader>
            <CardBody id="application-form">
              {/*
                The scroll target, and the anchor `goToForm` reaches for. The
                margin keeps it clear of the sticky mobile header.
              */}
              <div ref={form} className="scroll-mt-16">
              {data.application ? (
                <p className="text-body-md text-muted-foreground">
                  You already have an application for this job. Edit it from My applications while its window is open.
                </p>
              ) : eligibility.eligible ? (
                <ApplyApplicationForm
                  cycleId={data.cycle.id}
                  jobId={job.id}
                  enrollmentId={data.enrollment_id}
                  questions={data.apply_form.questions}
                  resumes={data.apply_form.resumes}
                />
              ) : (
                <div className="flex flex-col gap-gap-md">
                  <p className="text-body-md text-muted-foreground">
                    Apply is unavailable until every eligibility check passes.
                  </p>
                  <Reasons reasons={eligibility.reasons} />
                </div>
              )}
              </div>
            </CardBody>
          </Card>
        </div>

        <div className="flex flex-col gap-section-margin">
          <Card>
            <CardHeader>
              <CardTitle>Compensation</CardTitle>
            </CardHeader>
            <CardBody className="flex flex-col gap-gap-lg">
              {compensation.ctc_lpa ? (
                <div>
                  <p className="tabular text-display text-foreground">
                    ₹{compensation.ctc_lpa}
                  </p>
                  <p className="text-body-sm text-muted-foreground">
                    LPA
                    {/* JOB-2.1: the student sees their own number, never both. */}
                    {compensation.source === "program"
                      ? " — the figure for your program"
                      : ""}
                  </p>
                </div>
              ) : null}
              {compensation.stipend_month ? (
                <div>
                  <p className="tabular text-headline-lg text-foreground">
                    ₹{compensation.stipend_month}
                  </p>
                  <p className="text-body-sm text-muted-foreground">per month</p>
                </div>
              ) : null}
              {compensation.ctc_breakdown ? (
                <p className="whitespace-pre-wrap text-body-md text-foreground">
                  {compensation.ctc_breakdown}
                </p>
              ) : null}
              {!compensation.ctc_lpa && !compensation.stipend_month ? (
                <p className="text-body-md text-muted-foreground">Not published.</p>
              ) : null}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Eligibility</CardTitle>
            </CardHeader>
            <CardBody className="flex flex-col gap-gap-lg">
              <p className="text-body-md text-foreground">{eligibility.summary}</p>
              {eligibility.eligible ? (
                <p className="flex items-center gap-gap-md text-body-md text-success">
                  <CheckCircle2 aria-hidden className="h-4 w-4" />
                  You meet every requirement.
                </p>
              ) : (
                <Reasons reasons={eligibility.reasons} />
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Key dates</CardTitle>
            </CardHeader>
            <CardBody>
              <dl className="flex flex-col gap-gap-lg text-body-md">
                <div className="flex items-baseline justify-between gap-gap-lg">
                  <dt className="text-muted-foreground">Applications close</dt>
                  <dd className="text-right text-foreground">
                    {job.application_deadline
                      ? formatDateTime(job.application_deadline)
                      : "Not set"}
                  </dd>
                </div>
                {job.offer_acceptance_deadline ? (
                  <div className="flex items-baseline justify-between gap-gap-lg">
                    <dt className="text-muted-foreground">Offers must be answered by</dt>
                    <dd className="text-right text-foreground">
                      {formatDateTime(job.offer_acceptance_deadline)}
                    </dd>
                  </div>
                ) : null}
              </dl>
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}
