import { ArrowLeft, GripVertical, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import {
  payload,
  type BuilderPayload,
  type CompaniesPayload,
  type JobQuestion,
  type JobRound,
  type TaxonomiesPayload,
} from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { GrantOverride } from "@/components/GrantOverride";
import { SubjectOverrides } from "@/components/SubjectOverrides";
import { BulkRows, type BulkRow } from "@/components/BulkRows";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";
import { Tabs } from "@/components/ui/tabs";
import { RuleEditor, type Rule } from "./RuleEditor";
import { ImpactPanel } from "./ImpactPanel";

type Tab = "basics" | "rounds" | "questions" | "eligibility";

/**
 * The job builder — four tabs over one job (Behavior JOB-2, LLD §11.3).
 *
 * The rounds tab is absent, not disabled-and-empty, when the cycle does not
 * support rounds: JOB-6 says an open-cycle job carries none at all, and the
 * screen is told so by `cycle.supports_rounds` rather than inferring it.
 */
export function JobBuilder() {
  const { id = "" } = useParams();
  const [search] = useSearchParams();
  const cycleId = search.get("cycle_id") ?? "";
  const [tab, setTab] = useState<Tab>("basics");

  const screen = useScreen("staff/job/{id}/builder", {
    params: { id },
    query: { cycle_id: cycleId },
    enabled: Boolean(cycleId),
  });

  if (!cycleId) {
    return (
      <ErrorState
        error={null}
        title="Missing cycle"
        message="Open the builder from a cycle's job list so the correct cycle can be loaded."
        backHref="/staff/cycles"
      />
    );
  }
  if (screen.isPending) {
    return (
      <div className="flex flex-col gap-gap-lg">
        <Skeleton className="h-9 w-96" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<BuilderPayload>(screen.data);
  const archived = data.cycle.archived_at !== null;
  const cancelled = data.job.cancelled_at !== null;
  const locked = archived || cancelled;

  const tabs = [
    { id: "basics" as const, label: "Basics" },
    ...(data.cycle.supports_rounds
      ? [{ id: "rounds" as const, label: "Rounds", badge: data.job.rounds.length }]
      : []),
    { id: "questions" as const, label: "Questions", badge: data.job.questions.length },
    {
      id: "eligibility" as const,
      label: "Eligibility",
      badge: data.eligibility.impact.eligible_count,
    },
  ];

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link
            to={`/staff/cycles/${cycleId}/jobs`}
            className="inline-flex items-center gap-gap-tight hover:underline"
          >
            <ArrowLeft className="h-3 w-3" /> {data.cycle.name} jobs
          </Link>
        }
        title={data.job.title}
        subtitle={`${data.job.company.name}${data.job.location ? ` · ${data.job.location}` : ""}`}
        actions={
          <>
            {/* The board is where a published job is actually worked; the
                builder is where it is defined. */}
            <Button variant="secondary" asChild>
              <Link to={`/staff/jobs/${id}/board`}>Board</Link>
            </Button>
            {data.job.is_published ? (
              <PreviewConfirm
                command="unpublish_job"
                input={{ cycle_id: cycleId, job_id: id }}
                title="Unpublish this job?"
                description="Students stop seeing it. Applications already made are untouched."
                confirmLabel="Unpublish"
                destructive
                trigger={
                  <Button variant="destructive-ghost" disabled={locked}>
                    Unpublish
                  </Button>
                }
              />
            ) : (
              <PreviewConfirm
                command="publish_job"
                input={{ cycle_id: cycleId, job_id: id }}
                title="Publish this job?"
                description="Every eligible member of the cycle will see it and can apply."
                confirmLabel="Publish"
                trigger={
                  <Button variant="primary" disabled={locked}>
                    Publish
                  </Button>
                }
              />
            )}
            <CancelJob cycleId={cycleId} jobId={id} data={data} disabled={locked} />
          </>
        }
      />

      {cancelled ? (
        <div className="rounded border border-danger-border bg-danger-subtle p-container-padding">
          <p className="text-body-md font-semibold text-danger">This job is cancelled</p>
          <p className="mt-gap-tight text-body-md text-foreground">
            Its rounds, questions, and rule are kept exactly as they were — a cancelled job
            is still a record of what happened.
          </p>
        </div>
      ) : null}

      <JobOverrides
        cycleId={cycleId}
        jobId={id}
        data={data}
        disabled={locked}
      />

      <Tabs tabs={tabs} active={tab} onChange={setTab} />

      {tab === "basics" ? (
        <BasicsTab cycleId={cycleId} jobId={id} data={data} disabled={locked} />
      ) : tab === "rounds" ? (
        <RoundsTab cycleId={cycleId} jobId={id} data={data} disabled={locked} />
      ) : tab === "questions" ? (
        <QuestionsTab cycleId={cycleId} jobId={id} data={data} disabled={locked} />
      ) : (
        <EligibilityTab cycleId={cycleId} jobId={id} data={data} disabled={locked} />
      )}
    </>
  );
}

/* ----------------------------------------------------------- overrides --- */

function JobOverrides({
  cycleId,
  jobId,
  data,
  disabled,
}: {
  cycleId: string;
  jobId: string;
  data: BuilderPayload;
  disabled: boolean;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Job overrides</CardTitle>
        <GrantOverride
          scope={{ cycle_id: cycleId, job_id: jobId }}
          title={`Grant an override on ${data.job.title}?`}
          description="A standing exception for this job, for every member of the cycle. To except one student, grant it on their record instead."
          domains={data.override_domains}
          disabled={disabled}
        />
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        <p className="text-body-sm text-muted-foreground">
          Job-wide exceptions can affect eligibility, application and response
          deadlines, edits, withdrawals, outcomes, or offer caps. They do not
          change the eligibility rule itself.
        </p>
        <SubjectOverrides overrides={data.overrides} empty />
      </CardBody>
    </Card>
  );
}

/* ------------------------------------------------------------- basics --- */

/**
 * Exactly the fields `UpdateJobBasicsInput` names, and nothing else.
 *
 * The form is an untyped bag by necessity — one `set(key, value)` behind a
 * dozen controls — and spreading a bag into a typed input is the one place
 * TypeScript's excess-property check does not apply. The command input is
 * `extra="forbid"`, so anything the bag has picked up is a 422 reading "Extra
 * inputs are not permitted", named after a field the operator never saw. The
 * projection makes that impossible rather than making it rare.
 */
const BASICS_FIELDS = [
  "outcome",
  "company_id",
  "title",
  "description",
  "location",
  "sector_id",
  "ctc_lpa",
  "ctc_breakdown",
  "stipend_month",
  "application_deadline",
  "offer_acceptance_deadline",
  "program_ctc",
] as const;

function basicsInput(draft: Record<string, unknown>): Record<string, unknown> {
  const input: Record<string, unknown> = {};
  for (const key of BASICS_FIELDS) {
    if (key in draft) input[key] = draft[key];
  }
  if (Array.isArray(input["program_ctc"])) {
    // The screen ships each row with the program's *name* for display, and
    // `ProgramCtcRow` forbids it. Send the two columns the command owns.
    input["program_ctc"] = (
      input["program_ctc"] as { program_id: string; ctc_lpa: string }[]
    ).map((row) => ({ program_id: row.program_id, ctc_lpa: row.ctc_lpa }));
  }
  return input;
}

function BasicsTab({
  cycleId,
  jobId,
  data,
  disabled,
}: {
  cycleId: string;
  jobId: string;
  data: BuilderPayload;
  disabled: boolean;
}) {
  const save = useCommand("update_job_basics");
  const companies = useScreen("staff/companies");
  const taxonomies = useScreen("staff/taxonomies");
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const job = data.job;

  // The two `datetime-local` inputs need their own display string, which is
  // not a field of the command. It lives here rather than in `draft`, because
  // `draft` is spread into an `extra="forbid"` input: a key the schema does
  // not name is a 422 on save, and a spread is exactly what TypeScript cannot
  // check. CycleJobs' create form has always done it this way.
  const [deadlineLocal, setDeadlineLocal] = useState<string | null>(null);
  const [offerDeadlineLocal, setOfferDeadlineLocal] = useState<string | null>(null);
  const dirty =
    Object.keys(draft).length > 0 ||
    deadlineLocal !== null ||
    offerDeadlineLocal !== null;

  function discard() {
    setDraft({});
    setDeadlineLocal(null);
    setOfferDeadlineLocal(null);
  }

  const read = (key: string, fallback: unknown) =>
    key in draft ? draft[key] : fallback;
  const set = (key: string, value: unknown) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  const local = (value: string | null) => (value ? value.slice(0, 16) : "");
  const instant = (value: string) => (value ? new Date(value).toISOString() : null);
  const programs = taxonomies.data
    ? payload<TaxonomiesPayload>(taxonomies.data).programs
    : [];

  if (companies.isPending || taxonomies.isPending) {
    return <DependencySkeleton title="Basics" />;
  }
  if (companies.isError || taxonomies.isError) {
    const dependency = companies.isError ? companies : taxonomies;
    return (
      <Card>
        <CardHeader><CardTitle>Basics</CardTitle></CardHeader>
        <CardBody>
          <ErrorState error={dependency.error} onRetry={() => void dependency.refetch()} />
        </CardBody>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Basics</CardTitle>
        {dirty ? (
          <div className="flex items-center gap-gap-md">
            <Button variant="ghost" size="sm" onClick={discard}>
              Discard
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={save.isPending}
              onClick={() =>
                save.mutate(
                  {
                    input: {
                      cycle_id: cycleId,
                      job_id: jobId,
                      ...basicsInput(draft),
                    },
                  },
                  { onSuccess: discard },
                )
              }
            >
              Save changes
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {save.isError ? <ErrorState error={save.error} title="Could not save" /> : null}

        <div className="grid gap-gap-lg sm:grid-cols-2">
          <Field label="Title" required>
            {(field) => (
              <Input
                {...field}
                disabled={disabled}
                value={String(read("title", job.title) ?? "")}
                onChange={(event) => set("title", event.target.value)}
              />
            )}
          </Field>
          <Field label="Company">
            {(field) => (
              <Select
                {...field}
                disabled={disabled}
                value={String(read("company_id", job.company.id) ?? "")}
                onChange={(event) => set("company_id", event.target.value)}
              >
                {(companies.data
                  ? payload<CompaniesPayload>(companies.data).companies
                  : [job.company as { id: string; name: string }]
                ).map((company) => (
                  <option key={company.id} value={company.id}>
                    {company.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field
            label="Outcome"
            hint={
              data.cycle.outcome_is_fixed
                ? "Fixed by the cycle's kind."
                : "An open cycle carries both kinds, so this job must say which it is."
            }
          >
            {(field) => (
              <Select
                {...field}
                disabled={disabled || data.cycle.outcome_is_fixed}
                value={String(read("outcome", job.outcome) ?? "")}
                onChange={(event) => set("outcome", event.target.value)}
              >
                <option value="placement">Placement</option>
                <option value="internship">Internship</option>
              </Select>
            )}
          </Field>
          <Field label="Location">
            {(field) => (
              <Input
                {...field}
                disabled={disabled}
                value={String(read("location", job.location ?? "") ?? "")}
                onChange={(event) => set("location", event.target.value)}
              />
            )}
          </Field>
          <Field label="Sector" hint="Overrides the company's sector for this role.">
            {(field) => (
              <Select
                {...field}
                disabled={disabled}
                value={String(read("sector_id", job.sector_id ?? "") ?? "")}
                onChange={(event) => set("sector_id", event.target.value || null)}
              >
                <option value="">Use the company sector</option>
                {payload<TaxonomiesPayload>(taxonomies.data!).sectors.map((sector) => (
                  <option key={sector.id} value={sector.id}>{sector.name}</option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="CTC (LPA)" hint="The headline figure, before any per-program override.">
            {(field) => (
              <Input
                {...field}
                type="number"
                step="0.01"
                disabled={disabled}
                value={String(read("ctc_lpa", job.ctc_lpa ?? "") ?? "")}
                onChange={(event) =>
                  set("ctc_lpa", event.target.value === "" ? null : event.target.value)
                }
              />
            )}
          </Field>
          <Field label="Stipend (per month)">
            {(field) => (
              <Input
                {...field}
                type="number"
                disabled={disabled}
                value={String(read("stipend_month", job.stipend_month ?? "") ?? "")}
                onChange={(event) =>
                  set("stipend_month", event.target.value === "" ? null : event.target.value)
                }
              />
            )}
          </Field>
          <Field label="Application deadline">
            {(field) => (
              <Input
                {...field}
                type="datetime-local"
                disabled={disabled}
                value={deadlineLocal ?? local(job.application_deadline)}
                onChange={(event) => {
                  setDeadlineLocal(event.target.value);
                  set("application_deadline", instant(event.target.value));
                }}
              />
            )}
          </Field>
          {data.cycle.supports_offer_deadline ? (
            <Field label="Offer acceptance deadline">
              {(field) => (
                <Input
                  {...field}
                  type="datetime-local"
                  disabled={disabled}
                  value={
                    offerDeadlineLocal ?? local(job.offer_acceptance_deadline)
                  }
                  onChange={(event) => {
                    setOfferDeadlineLocal(event.target.value);
                    set("offer_acceptance_deadline", instant(event.target.value));
                  }}
                />
              )}
            </Field>
          ) : null}
        </div>

        <Field label="Description" required>
          {(field) => (
            <Textarea
              {...field}
              disabled={disabled}
              className="min-h-[160px]"
              value={String(read("description", job.description ?? "") ?? "")}
              onChange={(event) => set("description", event.target.value)}
            />
          )}
        </Field>

        <Field label="CTC breakdown" hint="Optional fixed, variable, bonus, and benefit details.">
          {(field) => (
            <Textarea
              {...field}
              disabled={disabled}
              value={String(read("ctc_breakdown", job.ctc_breakdown ?? "") ?? "")}
              onChange={(event) => set("ctc_breakdown", event.target.value || null)}
            />
          )}
        </Field>

        <ProgramCtc
          programs={programs}
          rows={
            (read("program_ctc", job.program_ctc) as {
              program_id: string;
              ctc_lpa: string;
            }[]) ?? []
          }
          disabled={disabled}
          onChange={(rows) => set("program_ctc", rows)}
        />
      </CardBody>
    </Card>
  );
}

/**
 * JOB-2.1 per-program compensation. A student sees their own number and not
 * both, so this table is the only place the difference is visible at all.
 */
function ProgramCtc({
  programs,
  rows,
  disabled,
  onChange,
}: {
  programs: { id: string; name: string }[];
  rows: { program_id: string; ctc_lpa: string }[];
  disabled: boolean;
  onChange: (rows: { program_id: string; ctc_lpa: string }[]) => void;
}) {
  const unused = programs.filter(
    (program) => !rows.some((row) => row.program_id === program.id),
  );
  return (
    <div className="flex flex-col gap-gap-md">
      <p className="text-body-sm font-semibold text-foreground">Per-program compensation</p>
      <p className="text-body-sm text-muted-foreground">
        Overrides the headline CTC for the programs named here. A student on one of them sees
        this figure instead, never both.
      </p>
      {rows.length === 0 ? (
        <p className="text-body-sm text-muted-foreground">No programme-specific figures.</p>
      ) : (
        <ul className="flex flex-col gap-gap-md">
          {rows.map((row, index) => (
            <li key={row.program_id} className="flex items-center gap-gap-md">
              <span className="min-w-40 text-body-md text-foreground">
                {programs.find((program) => program.id === row.program_id)?.name ??
                  row.program_id}
              </span>
              <Input
                aria-label="CTC for this program"
                type="number"
                step="0.01"
                className="w-40"
                disabled={disabled}
                value={row.ctc_lpa}
                onChange={(event) =>
                  onChange(
                    rows.map((item, i) =>
                      i === index ? { ...item, ctc_lpa: event.target.value } : item,
                    ),
                  )
                }
              />
              <Button
                variant="destructive-ghost"
                size="icon-sm"
                aria-label="Remove this program row"
                disabled={disabled}
                onClick={() => onChange(rows.filter((_, i) => i !== index))}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      {unused.length > 0 ? (
        <div>
          <Select
            aria-label="Add a program override"
            className="w-64"
            disabled={disabled}
            value=""
            onChange={(event) =>
              event.target.value &&
              onChange([...rows, { program_id: event.target.value, ctc_lpa: "" }])
            }
          >
            <option value="">Add a program…</option>
            {unused.map((program) => (
              <option key={program.id} value={program.id}>
                {program.name}
              </option>
            ))}
          </Select>
        </div>
      ) : null}
    </div>
  );
}

/* ------------------------------------------------------------- rounds --- */

interface RoundDraft {
  round_id: string | null;
  round_type_id: string;
  name: string;
  venue: string;
  /**
   * Carried through the save untouched: this tab has no schedule input, and a
   * payload that omitted it left the server to guess whether that meant
   * "unchanged" or "clear it". Sending it back is what makes the request say
   * what it means.
   */
  scheduled_at: string | null;
  duration_min: string;
  instructions: string;
  has_state: boolean;
}

function RoundsTab({
  cycleId,
  jobId,
  data,
  disabled,
}: {
  cycleId: string;
  jobId: string;
  data: BuilderPayload;
  disabled: boolean;
}) {
  const save = useCommand("upsert_job_rounds");
  const taxonomies = useScreen("staff/taxonomies");
  const roundTypes = taxonomies.data
    ? payload<TaxonomiesPayload>(taxonomies.data).round_types
    : [];
  const [rounds, setRounds] = useState<RoundDraft[]>(() => data.job.rounds.map(toDraft));

  if (taxonomies.isPending) {
    return <DependencySkeleton title="Rounds" />;
  }
  if (taxonomies.isError) {
    return (
      <Card>
        <CardHeader><CardTitle>Rounds</CardTitle></CardHeader>
        <CardBody>
          <ErrorState error={taxonomies.error} onRetry={() => void taxonomies.refetch()} />
        </CardBody>
      </Card>
    );
  }

  function move(index: number, delta: number) {
    const next = [...rounds];
    const target = index + delta;
    if (target < 0 || target >= next.length) return;
    const moved = next[index];
    const other = next[target];
    if (!moved || !other) return;
    next[index] = other;
    next[target] = moved;
    setRounds(next);
  }

  return (
    <div className="flex flex-col gap-section-margin">
      <Card>
        <CardHeader>
          <CardTitle>Rounds</CardTitle>
          <div className="flex items-center gap-gap-md">
            <Button
              variant="secondary"
              size="sm"
              icon={<Plus className="h-4 w-4" />}
              disabled={disabled || roundTypes.length === 0}
              onClick={() =>
                setRounds([
                  ...rounds,
                  {
                    round_id: null,
                    round_type_id: roundTypes[0]?.id ?? "",
                    name: "",
                    venue: "",
                    scheduled_at: null,
                    duration_min: "",
                    instructions: "",
                    has_state: false,
                  },
                ])
              }
            >
              Add round
            </Button>
            <PreviewConfirm
              command="upsert_job_rounds"
              input={{
                cycle_id: cycleId,
                job_id: jobId,
                rounds: rounds.map((round) => ({
                  ...(round.round_id ? { round_id: round.round_id } : {}),
                  round_type_id: round.round_type_id,
                  name: round.name.trim(),
                  venue: round.venue.trim() || null,
                  scheduled_at: round.scheduled_at,
                  duration_min: round.duration_min ? Number(round.duration_min) : null,
                  instructions: round.instructions.trim() || null,
                })),
              }}
              title="Save the round schedule?"
              description="Applicants in flight are notified when the order changes or a round is inserted."
              confirmLabel="Save rounds"
              trigger={
                <Button
                  variant="primary"
                  size="sm"
                  disabled={disabled || rounds.some((round) => !round.name.trim())}
                >
                  Save rounds
                </Button>
              }
            />
          </div>
        </CardHeader>
        <CardBody className="flex flex-col gap-gap-lg">
          {save.isError ? <ErrorState error={save.error} title="Could not save" /> : null}
          <p className="text-body-sm text-muted-foreground">
            Renaming and rescheduling a round is always allowed. A round somebody has already
            entered cannot be deleted — nothing an edit does may invalidate a recorded result.
          </p>

          {rounds.length === 0 ? (
            <EmptyState message="No rounds yet. Add the first one." />
          ) : (
            <ul className="flex flex-col gap-gap-lg">
              {rounds.map((round, index) => (
                <li
                  key={round.round_id ?? `new-${index}`}
                  className="rounded border border-border p-gap-lg"
                >
                  <div className="flex items-start gap-gap-md">
                    <div className="flex flex-col items-center gap-gap-tight pt-gap-md">
                      <GripVertical aria-hidden className="h-4 w-4 text-muted-foreground" />
                      <span className="tabular text-body-sm text-muted-foreground">
                        {index + 1}
                      </span>
                    </div>
                    <div className="grid flex-1 gap-gap-lg sm:grid-cols-2">
                      <Field label="Name" required>
                        {(field) => (
                          <Input
                            {...field}
                            disabled={disabled}
                            value={round.name}
                            onChange={(event) =>
                              setRounds(
                                rounds.map((item, i) =>
                                  i === index ? { ...item, name: event.target.value } : item,
                                ),
                              )
                            }
                          />
                        )}
                      </Field>
                      <Field label="Type">
                        {(field) => (
                          <Select
                            {...field}
                            disabled={disabled}
                            value={round.round_type_id}
                            onChange={(event) =>
                              setRounds(
                                rounds.map((item, i) =>
                                  i === index
                                    ? { ...item, round_type_id: event.target.value }
                                    : item,
                                ),
                              )
                            }
                          >
                            {roundTypes.map((type) => (
                              <option key={type.id} value={type.id}>
                                {type.name}
                              </option>
                            ))}
                          </Select>
                        )}
                      </Field>
                      <Field label="Venue">
                        {(field) => (
                          <Input
                            {...field}
                            disabled={disabled}
                            value={round.venue}
                            onChange={(event) =>
                              setRounds(
                                rounds.map((item, i) =>
                                  i === index ? { ...item, venue: event.target.value } : item,
                                ),
                              )
                            }
                          />
                        )}
                      </Field>
                      <Field label="Duration (minutes)">
                        {(field) => (
                          <Input
                            {...field}
                            type="number"
                            disabled={disabled}
                            value={round.duration_min}
                            onChange={(event) =>
                              setRounds(
                                rounds.map((item, i) =>
                                  i === index
                                    ? { ...item, duration_min: event.target.value }
                                    : item,
                                ),
                              )
                            }
                          />
                        )}
                      </Field>
                    </div>
                    <div className="flex flex-col gap-gap-tight">
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Move up"
                        disabled={disabled || index === 0}
                        onClick={() => move(index, -1)}
                      >
                        ↑
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon-sm"
                        aria-label="Move down"
                        disabled={disabled || index === rounds.length - 1}
                        onClick={() => move(index, 1)}
                      >
                        ↓
                      </Button>
                      <Button
                        variant="destructive-ghost"
                        size="icon-sm"
                        aria-label="Remove round"
                        title={
                          round.has_state
                            ? "Somebody has entered this round, so it cannot be deleted"
                            : undefined
                        }
                        disabled={disabled || round.has_state}
                        onClick={() => setRounds(rounds.filter((_, i) => i !== index))}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function toDraft(round: JobRound): RoundDraft {
  return {
    round_id: round.round_id,
    round_type_id: round.round_type_id,
    name: round.name,
    venue: round.venue ?? "",
    scheduled_at: round.scheduled_at ?? null,
    duration_min: round.duration_min === null ? "" : String(round.duration_min),
    instructions: round.instructions ?? "",
    has_state: round.deletable === false,
  };
}

/* ---------------------------------------------------------- questions --- */

interface QuestionDraft {
  question_id: string | null;
  text: string;
  qtype: string;
  required: boolean;
  options: string[];
  answered: boolean;
}

const QUESTION_TYPES = [
  { value: "text", label: "Short text" },
  { value: "longtext", label: "Long text" },
  { value: "single", label: "Choose one" },
  { value: "multi", label: "Choose several" },
  { value: "boolean", label: "Yes / no" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "email", label: "Email" },
  { value: "url", label: "Link" },
];

const OPTION_TYPES = new Set(["single", "multi"]);

function QuestionsTab({
  cycleId,
  jobId,
  data,
  disabled,
}: {
  cycleId: string;
  jobId: string;
  data: BuilderPayload;
  disabled: boolean;
}) {
  const [questions, setQuestions] = useState<QuestionDraft[]>(() =>
    data.job.questions.map(toQuestionDraft),
  );

  const update = (index: number, patch: Partial<QuestionDraft>) =>
    setQuestions(questions.map((item, i) => (i === index ? { ...item, ...patch } : item)));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Application form</CardTitle>
        <div className="flex items-center gap-gap-md">
          <Button
            variant="secondary"
            size="sm"
            icon={<Plus className="h-4 w-4" />}
            disabled={disabled}
            onClick={() =>
              setQuestions([
                ...questions,
                {
                  question_id: null,
                  text: "",
                  qtype: "text",
                  required: false,
                  options: [],
                  answered: false,
                },
              ])
            }
          >
            Add question
          </Button>
          <PreviewConfirm
            command="upsert_job_questions"
            input={{
              cycle_id: cycleId,
              job_id: jobId,
              questions: questions.map((question) => ({
                ...(question.question_id ? { question_id: question.question_id } : {}),
                text: question.text.trim(),
                qtype: question.qtype as "text",
                required: question.required,
                options: OPTION_TYPES.has(question.qtype)
                  ? question.options.filter((option) => option.trim())
                  : [],
              })),
            }}
            title="Save the application form?"
            confirmLabel="Save questions"
            trigger={
              <Button
                variant="primary"
                size="sm"
                disabled={disabled || questions.some((question) => !question.text.trim())}
              >
                Save questions
              </Button>
            }
          />
        </div>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        <p className="text-body-sm text-muted-foreground">
          A question somebody has answered cannot be removed, retyped, or have an option taken
          away — each of those would change what a stored answer means. Renaming it and adding
          an option stay free.
        </p>

        {questions.length === 0 ? (
          <EmptyState message="No questions. Students will apply with their profile and resume alone." />
        ) : (
          <ul className="flex flex-col gap-gap-lg">
            {questions.map((question, index) => (
              <li
                key={question.question_id ?? `new-${index}`}
                className="rounded border border-border p-gap-lg"
              >
                <div className="flex items-start gap-gap-lg">
                  <div className="grid flex-1 gap-gap-lg sm:grid-cols-[2fr_1fr]">
                    <Field label="Question" required>
                      {(field) => (
                        <Input
                          {...field}
                          disabled={disabled}
                          value={question.text}
                          onChange={(event) => update(index, { text: event.target.value })}
                        />
                      )}
                    </Field>
                    <Field
                      label="Answer type"
                      {...(question.answered
                        ? { hint: "Locked — this question has been answered." }
                        : {})}
                    >
                      {(field) => (
                        <Select
                          {...field}
                          disabled={disabled || question.answered}
                          value={question.qtype}
                          onChange={(event) =>
                            update(index, {
                              qtype: event.target.value,
                              options: OPTION_TYPES.has(event.target.value)
                                ? question.options
                                : [],
                            })
                          }
                        >
                          {QUESTION_TYPES.map((type) => (
                            <option key={type.value} value={type.value}>
                              {type.label}
                            </option>
                          ))}
                        </Select>
                      )}
                    </Field>
                  </div>
                  <Button
                    variant="destructive-ghost"
                    size="icon-sm"
                    aria-label="Remove question"
                    title={
                      question.answered
                        ? "Somebody has answered this, so it cannot be removed"
                        : undefined
                    }
                    disabled={disabled || question.answered}
                    onClick={() => setQuestions(questions.filter((_, i) => i !== index))}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>

                <label className="mt-gap-lg flex items-center gap-gap-md text-body-md text-foreground">
                  <Checkbox
                    disabled={disabled}
                    checked={question.required}
                    onChange={(event) => update(index, { required: event.target.checked })}
                  />
                  Required
                </label>

                {OPTION_TYPES.has(question.qtype) ? (
                  <Options
                    options={question.options}
                    answered={question.answered}
                    disabled={disabled}
                    onChange={(options) => update(index, { options })}
                  />
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function Options({
  options,
  answered,
  disabled,
  onChange,
}: {
  options: string[];
  answered: boolean;
  disabled: boolean;
  onChange: (options: string[]) => void;
}) {
  return (
    <div className="mt-gap-lg flex flex-col gap-gap-md">
      <p className="text-body-sm font-semibold text-foreground">Options</p>
      {answered ? (
        <p className="text-body-sm text-muted-foreground">
          Options may be added but not removed — an answer already given must keep meaning what
          it meant.
        </p>
      ) : null}
      {options.length === 0 ? (
        <p className="text-body-sm text-muted-foreground">No options yet.</p>
      ) : null}
      {options.map((option, index) => (
        <div key={index} className="flex items-center gap-gap-md">
          <Input
            aria-label={`Option ${index + 1}`}
            className="max-w-sm"
            disabled={disabled}
            value={option}
            onChange={(event) =>
              onChange(options.map((item, i) => (i === index ? event.target.value : item)))
            }
          />
          <Button
            variant="destructive-ghost"
            size="icon-sm"
            aria-label={`Remove option ${index + 1}`}
            disabled={disabled || answered}
            onClick={() => onChange(options.filter((_, i) => i !== index))}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      ))}
      <div>
        <Button
          variant="secondary"
          size="sm"
          disabled={disabled}
          icon={<Plus className="h-4 w-4" />}
          onClick={() => onChange([...options, ""])}
        >
          Add option
        </Button>
      </div>
    </div>
  );
}

function toQuestionDraft(question: JobQuestion): QuestionDraft {
  return {
    question_id: question.question_id,
    text: question.text,
    qtype: question.qtype,
    required: question.required,
    options: question.options,
    answered: (question.answer_count ?? 0) > 0 || question.removable === false,
  };
}

/* -------------------------------------------------------- eligibility --- */

function EligibilityTab({
  cycleId,
  jobId,
  data,
  disabled,
}: {
  cycleId: string;
  jobId: string;
  data: BuilderPayload;
  disabled: boolean;
}) {
  const taxonomies = useScreen("staff/taxonomies");
  const [rule, setRule] = useState<Rule | null>(data.eligibility.rule);
  const save = useCommand("update_job_eligibility");
  const taxonomy = taxonomies.data
    ? payload<TaxonomiesPayload>(taxonomies.data)
    : { programs: [], branches: [], minors: [] };

  if (taxonomies.isPending) {
    return <DependencySkeleton title="Eligibility rule" />;
  }
  if (taxonomies.isError) {
    return (
      <Card>
        <CardHeader><CardTitle>Eligibility rule</CardTitle></CardHeader>
        <CardBody>
          <ErrorState error={taxonomies.error} onRetry={() => void taxonomies.refetch()} />
        </CardBody>
      </Card>
    );
  }

  return (
    <div className="grid gap-section-margin lg:grid-cols-[3fr_2fr]">
      <Card>
        <CardHeader>
          <CardTitle>Eligibility rule</CardTitle>
          <div className="flex items-center gap-gap-md">
            <PreviewConfirm
              command="update_job_eligibility"
              input={{ cycle_id: cycleId, job_id: jobId, eligibility_rule: rule }}
              title="Save this eligibility rule?"
              description="Students who already applied under the old rule keep their applications — an eligibility edit never reaches back."
              confirmLabel="Save rule"
              trigger={
                <Button variant="primary" size="sm" disabled={disabled}>
                  Save rule
                </Button>
              }
            />
          </div>
        </CardHeader>
        <CardBody className="flex flex-col gap-gap-lg">
          {save.isError ? <ErrorState error={save.error} title="Could not save" /> : null}
          <div className="rounded border border-border bg-muted p-gap-lg">
            <p className="text-label-caps uppercase text-muted-foreground">
              What students will read
            </p>
            <p className="mt-gap-md text-body-md text-foreground">
              {data.eligibility.summary}
            </p>
          </div>
          <RuleEditor
            rule={rule}
            taxonomy={{
              programs: taxonomy.programs,
              branches: taxonomy.branches,
              minors: taxonomy.minors,
            }}
            disabled={disabled}
            onChange={setRule}
          />
        </CardBody>
      </Card>

      <ImpactPanel
        cycleId={cycleId}
        jobId={jobId}
        rule={rule}
        saved={data.eligibility.rule}
        impact={data.eligibility.impact}
      />
    </div>
  );
}

function DependencySkeleton({ title }: { title: string }) {
  return (
    <Card>
      <CardHeader><CardTitle>{title}</CardTitle></CardHeader>
      <CardBody className="grid gap-gap-lg sm:grid-cols-2">
        <Skeleton className="h-control w-full" />
        <Skeleton className="h-control w-full" />
        <Skeleton className="h-32 w-full sm:col-span-2" />
      </CardBody>
    </Card>
  );
}

/* ------------------------------------------------------------- cancel --- */

function CancelJob({
  cycleId,
  jobId,
  data,
  disabled,
}: {
  cycleId: string;
  jobId: string;
  data: BuilderPayload;
  disabled: boolean;
}) {
  const targets = data.cancellation_preview.targets;
  const untouched = data.cancellation_preview.untouched;

  return (
    <PreviewConfirm
      command="cancel_job"
      input={{
        cycle_id: cycleId,
        job_id: jobId,
        reason: "",
        batch_key: `cancel-${jobId}`,
        rows: [...targets, ...untouched].map((row) => ({
          application_id: row.application_id,
        })),
      }}
      title="Cancel this job?"
      description={
        untouched.length > 0
          ? `${targets.length} application${targets.length === 1 ? "" : "s"} will be rejected. ${untouched.length} accepted application${untouched.length === 1 ? " is" : "s are"} left untouched — unwinding those is terminate_offer's job.`
          : `${targets.length} application${targets.length === 1 ? "" : "s"} will be rejected and any open offer revoked.`
      }
      confirmLabel="Cancel job"
      destructive
      renderSummary={(summary) => (
        <BulkRows
          summary={summary as never}
          applyLabel="Will be rejected"
          // JOB-5's point is which applications the cancellation does *not*
          // touch, so the accepted ones must arrive named rather than as a
          // count of skipped rows. The command reports ids; the screen's own
          // preview lists are where the names are.
          resolveName={(row: BulkRow) =>
            [...targets, ...untouched].find(
              (candidate) => candidate.application_id === row.application_id,
            )?.full_name
          }
        />
      )}
      choices={[
        {
          name: "reason",
          label: "Reason",
          kind: "textarea",
          required: true,
          hint: "Sent to every affected student.",
        },
      ]}
      trigger={
        <Button variant="destructive-ghost" disabled={disabled}>
          Cancel job
        </Button>
      }
    />
  );
}
