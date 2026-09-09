import { ArrowLeft, Briefcase, Plus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  payload,
  type CompaniesPayload,
  type StaffCycleJobsPayload,
} from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select, Textarea } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/ui/table";
import { EmptyState, ErrorState, Skeleton, TableSkeleton } from "@/components/ui/states";
import { formatDate } from "@/lib/date";
import { counted } from "@/lib/text";

type Job = StaffCycleJobsPayload["jobs"][number];

/** Every job in one cycle (LLD §11.3 `staff/cycle/{id}/jobs`). */
export function CycleJobs() {
  const { id = "" } = useParams();
  const [includeCancelled, setIncludeCancelled] = useState(true);
  const [creating, setCreating] = useState(false);
  const screen = useScreen("staff/cycle/{id}/jobs", {
    params: { id },
    query: { include_cancelled: includeCancelled },
  });

  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = screen.data ? payload<StaffCycleJobsPayload>(screen.data) : undefined;

  const columns: Column<Job>[] = [
    {
      key: "title",
      header: "Job",
      cell: (job) => (
        <div className="flex flex-col">
          <Link
            to={`/staff/jobs/${job.id}?cycle_id=${id}`}
            className="font-medium text-accent hover:underline"
          >
            {job.title}
          </Link>
          <span className="text-body-sm text-muted-foreground">
            {job.company.name}
            {job.location ? ` · ${job.location}` : ""}
          </span>
        </div>
      ),
    },
    {
      key: "state",
      header: "State",
      cell: (job) =>
        job.cancelled_at ? (
          <span className="text-danger">Cancelled</span>
        ) : job.is_published ? (
          "Published"
        ) : (
          <span className="text-muted-foreground">Draft</span>
        ),
    },
    {
      key: "ctc",
      header: "CTC (LPA)",
      numeric: true,
      cell: (job) => job.ctc_lpa ?? <span className="text-muted-foreground">—</span>,
    },
    { key: "rounds", header: "Rounds", numeric: true, cell: (job) => job.round_count },
    {
      key: "questions",
      header: "Questions",
      numeric: true,
      cell: (job) => job.question_count,
    },
    {
      key: "applications",
      header: "Applicants",
      numeric: true,
      cell: (job) => job.application_count,
    },
    {
      key: "deadline",
      header: "Deadline",
      cell: (job) =>
        job.application_deadline ? (
          formatDate(job.application_deadline)
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link
            to={`/staff/cycles/${id}`}
            className="inline-flex items-center gap-gap-tight hover:underline"
          >
            <ArrowLeft className="h-3 w-3" /> {data?.cycle.name ?? "Cycle"}
          </Link>
        }
        title="Jobs"
        subtitle="Draft jobs are invisible to students until you publish them."
        actions={
          <Button
            variant="primary"
            icon={<Plus className="h-4 w-4" />}
            onClick={() => setCreating((open) => !open)}
          >
            New job
          </Button>
        }
      />

      {creating ? (
        <CreateJobCard
          cycleId={id}
          cycleKind={data?.cycle.kind ?? "placement"}
          onDone={() => setCreating(false)}
        />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{data ? counted(data.jobs.length, "job") : "Jobs"}</CardTitle>
          <label className="flex items-center gap-gap-md text-body-md text-foreground">
            <Checkbox
              checked={includeCancelled}
              onChange={(event) => setIncludeCancelled(event.target.checked)}
            />
            Show cancelled
          </label>
        </CardHeader>
        {screen.isPending ? (
          <TableSkeleton />
        ) : (
          <DataTable
            columns={columns}
            rows={data?.jobs ?? []}
            rowKey={(job) => job.id}
            empty={
              <CardBody>
                <EmptyState
                  icon={<Briefcase className="h-8 w-8" />}
                  message="No jobs in this cycle yet."
                />
              </CardBody>
            }
          />
        )}
      </Card>
    </>
  );
}

function CreateJobCard({
  cycleId,
  cycleKind,
  onDone,
}: {
  cycleId: string;
  cycleKind: string;
  onDone: () => void;
}) {
  const create = useCommand("create_job");
  const companies = useScreen("staff/companies");
  const [title, setTitle] = useState("");
  const [companyId, setCompanyId] = useState("");
  const [description, setDescription] = useState("");
  const [outcome, setOutcome] = useState("placement");
  const [deadline, setDeadline] = useState("");
  // Reachable on the edit screen a moment later, which is one round trip
  // per job — and in a real season most jobs carry a stipend or a CTC
  // breakdown, so most jobs paid it.
  const [offerDeadline, setOfferDeadline] = useState("");
  const [stipend, setStipend] = useState("");
  const [ctcBreakdown, setCtcBreakdown] = useState("");
  const list = companies.data ? payload<CompaniesPayload>(companies.data).companies : [];
  // JOB-6: an open cycle carries both kinds, so the job must say which it is.
  const outcomeIsFixed = cycleKind !== "open";

  return (
    <Card>
      <CardHeader>
        <CardTitle>New job</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {companies.isError ? (
          <ErrorState error={companies.error} onRetry={() => void companies.refetch()} title="Could not load companies" />
        ) : null}
        {create.isError ? <ErrorState error={create.error} title="Could not create" /> : null}
        {companies.isPending ? (
          <div className="grid gap-gap-lg sm:grid-cols-2">
            <Skeleton className="h-control w-full" />
            <Skeleton className="h-control w-full" />
          </div>
        ) : null}
        <div className="grid gap-gap-lg sm:grid-cols-2">
          <Field label="Title" required>
            {(field) => (
              <Input
                {...field}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            )}
          </Field>
          <Field label="Company" required>
            {(field) => (
              <Select
                {...field}
                value={companyId}
                onChange={(event) => setCompanyId(event.target.value)}
              >
                <option value="">Select a company…</option>
                {list.map((company) => (
                  <option key={company.id} value={company.id}>
                    {company.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          {outcomeIsFixed ? null : (
            <Field
              label="Outcome"
              required
              hint="This cycle carries both kinds, so the job must say which it is."
            >
              {(field) => (
                <Select
                  {...field}
                  value={outcome}
                  onChange={(event) => setOutcome(event.target.value)}
                >
                  <option value="placement">Placement</option>
                  <option value="internship">Internship</option>
                </Select>
              )}
            </Field>
          )}
          <Field
            label="Application deadline"
            {...(outcomeIsFixed ? { required: true } : {})}
          >
            {(field) => (
              <Input
                {...field}
                type="datetime-local"
                value={deadline}
                onChange={(event) => setDeadline(event.target.value)}
              />
            )}
          </Field>
          <Field
            label="Offer response deadline"
            hint="Absent means no expiry automation: an unanswered offer stays open."
          >
            {(field) => (
              <Input
                {...field}
                type="datetime-local"
                value={offerDeadline}
                onChange={(event) => setOfferDeadline(event.target.value)}
              />
            )}
          </Field>
          <Field label="Stipend per month" hint="Internship compensation, in rupees.">
            {(field) => (
              <Input
                {...field}
                type="number"
                step="0.01"
                value={stipend}
                onChange={(event) => setStipend(event.target.value)}
              />
            )}
          </Field>
        </div>
        <Field label="CTC breakdown" hint="Free text: base, bonus, and what is conditional.">
          {(field) => (
            <Textarea
              {...field}
              value={ctcBreakdown}
              onChange={(event) => setCtcBreakdown(event.target.value)}
            />
          )}
        </Field>
        <Field label="Description" required>
          {(field) => (
            <Textarea
              {...field}
              className="min-h-[120px]"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          )}
        </Field>
        <div className="flex items-center gap-gap-md">
          <Button
            variant="primary"
            disabled={companies.isPending || companies.isError || !title.trim() || !companyId || !description.trim()}
            loading={create.isPending}
            onClick={() =>
              create.mutate(
                {
                  input: {
                    cycle_id: cycleId,
                    company_id: companyId,
                    title: title.trim(),
                    description: description.trim(),
                    program_ctc: [],
                    ...(outcomeIsFixed ? {} : { outcome: outcome as "placement" }),
                    application_deadline: deadline
                      ? new Date(deadline).toISOString()
                      : null,
                    offer_acceptance_deadline: offerDeadline
                      ? new Date(offerDeadline).toISOString()
                      : null,
                    stipend_month: stipend ? Number(stipend) : null,
                    ctc_breakdown: ctcBreakdown.trim() || null,
                  },
                },
                { onSuccess: onDone },
              )
            }
          >
            Create job
          </Button>
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
        <p className="text-body-sm text-muted-foreground">
          The job is created as a draft. Rounds, questions, and the eligibility rule are set
          in the builder, and nothing is visible to students until you publish.
        </p>
      </CardBody>
    </Card>
  );
}
