import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { payload, type StaffJobOffersPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { BulkBar } from "@/components/BulkBar";
import { BulkRows, type BulkRow } from "@/components/BulkRows";
import { TerminationPlan } from "@/components/CommandSummaryDetails";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select } from "@/components/ui/input";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDateTime } from "@/lib/date";
import { newIdempotencyKey } from "@/lib/idempotency";
import { humanise } from "@/lib/text";

type Data = StaffJobOffersPayload;
type Row = Data["applications"][number];

export function Offers() {
  const { id = "" } = useParams();
  const screen = useScreen("staff/job/{id}/offers", { params: { id } });
  const [selected, setSelected] = useState<string[]>([]);
  const batchKey = useMemo(() => newIdempotencyKey(), [selected.join(",")]);

  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }
  const data = payload<Data>(screen.data);
  const frozen = data.cycle.archived || data.job.cancelled;

  return (
    <>
      <PageHeader
        title={`${data.job.title} offers`}
        subtitle={`${data.job.company} · ${data.cycle.name}`}
        actions={
          <Button variant="secondary" asChild>
            <Link to={`/staff/jobs/${data.job.id}/board`}>Pipeline board</Link>
          </Button>
        }
      />

      {!frozen ? (
        <BulkBar
          selected={selected}
          onChange={setSelected}
          identifierLabel="roll numbers or emails"
          actions={
            <div className="flex flex-wrap gap-gap-md">
              <PreviewConfirm
                command="extend_offers"
                input={{
                  cycle_id: data.cycle.id,
                  job_id: data.job.id,
                  rows: selected.map(identifierRow),
                  batch_key: batchKey,
                }}
                title={`Extend ${selected.length} offer${selected.length === 1 ? "" : "s"}?`}
                confirmLabel="Extend offers"
                renderSummary={(summary) => (
                  <BulkRows
                    summary={summary as never}
                    applyLabel="Will be offered"
                    resolveName={(row: BulkRow) => applicantName(data, row)}
                  />
                )}
                trigger={
                  <Button disabled={selected.length === 0 || !data.actions.extend.allowed}>
                    Extend / rollout
                  </Button>
                }
                onDone={() => setSelected([])}
              />
              {data.actions.record_open_outcome.allowed ? (
                <OpenOutcome
                  cycleId={data.cycle.id}
                  jobId={data.job.id}
                  selected={selected}
                  batchKey={batchKey}
                  applicants={
                    new Map(
                      data.applications.map((row) => [row.application_id, row.full_name]),
                    )
                  }
                  onDone={() => setSelected([])}
                />
              ) : null}
            </div>
          }
        />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-gap-md">
            {frozen || data.applications.length === 0 ? null : (
              <Checkbox
                aria-label="Select every application"
                checked={
                  selected.length > 0 &&
                  data.applications.every((row) => selected.includes(row.application_id))
                }
                onChange={(event) =>
                  setSelected(
                    event.target.checked
                      ? data.applications.map((row) => row.application_id)
                      : [],
                  )
                }
              />
            )}
            Applications ({data.applications.length})
          </CardTitle>
        </CardHeader>
        <CardBody>
          {data.applications.length === 0 ? (
            <EmptyState message="No applications have reached this job." />
          ) : (
            <ul className="flex flex-col gap-gap-md">
              {data.applications.map((row) => (
                <OfferRow
                  key={row.application_id}
                  row={row}
                  cycleId={data.cycle.id}
                  jobId={data.job.id}
                  selected={selected.includes(row.application_id)}
                  frozen={frozen}
                  onSelect={(checked) =>
                    setSelected((current) =>
                      checked
                        ? [...current, row.application_id]
                        : current.filter((item) => item !== row.application_id),
                    )
                  }
                />
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </>
  );
}

function OfferRow({
  row,
  cycleId,
  jobId,
  selected,
  frozen,
  onSelect,
}: {
  row: Row;
  cycleId: string;
  jobId: string;
  selected: boolean;
  frozen: boolean;
  onSelect: (checked: boolean) => void;
}) {
  return (
    <li className="rounded border border-border p-gap-lg">
      <div className="flex flex-wrap items-center gap-gap-md">
        {!frozen && row.actions.extend.allowed ? (
          <Checkbox
            checked={selected}
            onChange={(event) => onSelect(event.target.checked)}
            aria-label={`Select ${row.full_name}`}
          />
        ) : null}
        <div className="min-w-0 flex-1">
          <p className="text-body-md font-medium text-foreground">{row.full_name}</p>
          <p className="text-body-sm text-muted-foreground">
            {[row.roll_number, row.email].filter(Boolean).join(" · ")}
          </p>
          {row.offer?.deadline_at ? (
            <p className="text-body-sm text-muted-foreground">
              Deadline {formatDateTime(row.offer.deadline_at)}
            </p>
          ) : null}
        </div>
        <StatusChip domain="application" value={row.status} />
        {row.actions.terminate.allowed && row.offer ? (
          <Termination row={row} cycleId={cycleId} jobId={jobId} />
        ) : null}
        {row.actions.re_extend.allowed && row.offer ? (
          <PreviewConfirm
            command="re_extend_offer"
            input={{
              cycle_id: cycleId,
              job_id: jobId,
              application_id: row.application_id,
              offer_id: row.offer.id,
              expected_status: row.status as "declined" | "offer_terminated",
              reason: "",
              notify: true,
            }}
            title={`Re-extend ${row.full_name}'s offer?`}
            confirmLabel="Re-extend"
            choices={[
              {
                name: "reason",
                label: "Reason",
                kind: "textarea",
                required: true,
              },
              {
                name: "deadline_at",
                label: "New deadline (optional ISO date/time)",
              },
            ]}
            trigger={<Button variant="secondary">Re-extend</Button>}
          />
        ) : null}
      </div>
      {!row.actions.terminate.allowed && row.actions.terminate.human ? (
        <p className="mt-gap-tight text-body-sm text-muted-foreground">
          {row.actions.terminate.human}
        </p>
      ) : null}
    </li>
  );
}

function Termination({ row, cycleId, jobId }: { row: Row; cycleId: string; jobId: string }) {
  const [selected, setSelected] = useState<string[]>(() =>
    row.restoration_candidates
      .filter((candidate) => candidate.selected && candidate.can_restore)
      .map((candidate) => candidate.application_id),
  );
  const [deadlines, setDeadlines] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      row.restoration_candidates
        .filter((candidate) => candidate.deadline_at)
        .map((candidate) => [candidate.application_id, localDateTime(candidate.deadline_at!)]),
    ),
  );
  const [notify, setNotify] = useState(true);
  const restore = row.restoration_candidates
    .filter((candidate) => selected.includes(candidate.application_id))
    .map((candidate) => ({
      application_id: candidate.application_id,
      deadline_at: deadlines[candidate.application_id]
        ? new Date(deadlines[candidate.application_id]!).toISOString()
        : null,
    }));

  const restorationChoices = (
    <div className="flex flex-col gap-gap-lg rounded border border-border p-gap-lg">
      <p className="text-label-caps uppercase text-muted-foreground">
        Restoration choices ({row.restoration_candidates.length})
      </p>
      {row.restoration_candidates.length === 0 ? (
        <p className="text-body-sm text-muted-foreground">
          No application was moved by this acceptance.
        </p>
      ) : (
        row.restoration_candidates.map((candidate) => {
          const checked = selected.includes(candidate.application_id);
          return (
            <div key={candidate.application_id} className="flex flex-col gap-gap-md">
              <label className="flex items-start gap-gap-md text-body-sm">
                <Checkbox
                  checked={checked}
                  disabled={!candidate.can_restore}
                  aria-label={`Restore ${candidate.job}`}
                  onChange={(event) =>
                    setSelected((current) =>
                      event.target.checked
                        ? [...current, candidate.application_id]
                        : current.filter((item) => item !== candidate.application_id),
                    )
                  }
                />
                <span>
                  <span className="block text-foreground">
                    {candidate.job} · {candidate.company}
                  </span>
                  <span className="flex flex-wrap items-center gap-gap-md text-muted-foreground">
                    <StatusChip domain="application" value={candidate.current_status} />
                    <span aria-hidden>→</span>
                    <StatusChip domain="application" value={candidate.restore_status} />
                    {candidate.target_round_id ? <span>prior round restored</span> : null}
                    {candidate.requires_fresh_offer ? <span>fresh offer row</span> : null}
                  </span>
                  {!candidate.can_restore && candidate.blocked_reason ? (
                    <span className="block text-danger">{candidate.blocked_reason}</span>
                  ) : null}
                </span>
              </label>
              {checked && candidate.deadline_editable ? (
                <Field
                  label={`Fresh offer deadline for ${candidate.job} (optional)`}
                  hint="Leave blank to create the fresh offer without a deadline."
                >
                  {(field) => (
                    <Input
                      {...field}
                      type="datetime-local"
                      value={deadlines[candidate.application_id] ?? ""}
                      onChange={(event) =>
                        setDeadlines((current) => ({
                          ...current,
                          [candidate.application_id]: event.target.value,
                        }))
                      }
                    />
                  )}
                </Field>
              ) : null}
            </div>
          );
        })
      )}
      <label className="flex items-center gap-gap-tight text-body-sm text-muted-foreground">
        <Checkbox checked={notify} onChange={(event) => setNotify(event.target.checked)} />
        Notify student
      </label>
    </div>
  );

  return (
    <PreviewConfirm
      command="terminate_offer"
      input={{
        cycle_id: cycleId,
        job_id: jobId,
        application_id: row.application_id,
        offer_id: row.offer!.id,
        expected_status: row.status as "offered" | "accepted",
        termination_kind: "admin_correction",
        reason: "",
        restore,
        notify,
      }}
      title={`Terminate ${row.full_name}'s offer?`}
      confirmLabel="Terminate offer"
      destructive
      choices={[
        {
          name: "termination_kind",
          label: "Kind",
          kind: "select",
          required: true,
          options: [
            { value: "company_revoked", label: "Company revoked" },
            { value: "student_renege", label: "Student renege" },
            { value: "admin_correction", label: "Administrative correction" },
          ],
        },
        { name: "reason", label: "Reason", kind: "textarea", required: true },
        {
          name: "discipline",
          label: "Discipline (optional)",
          kind: "select",
          options: [
            { value: "strike", label: "Award strike" },
            { value: "penalty", label: "Award direct penalty" },
          ],
        },
      ]}
      choiceContent={restorationChoices}
      renderSummary={(summary) => (
        <TerminationPlan summary={summary as unknown as Record<string, unknown>} />
      )}
      trigger={<Button variant="destructive-ghost">Terminate</Button>}
    />
  );
}

function localDateTime(value: string): string {
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function OpenOutcome({
  cycleId,
  jobId,
  selected,
  batchKey,
  applicants,
  onDone,
}: {
  cycleId: string;
  jobId: string;
  selected: readonly string[];
  batchKey: string;
  /** application_id → name, so the preview names people and not ids. */
  applicants: Map<string, string>;
  onDone: () => void;
}) {
  const [target, setTarget] = useState("offered");
  return (
    <div className="flex items-center gap-gap-tight">
      <Field label="Outcome">
        {(field) => (
          <Select {...field} value={target} onChange={(event) => setTarget(event.target.value)}>
            {['offered', 'accepted', 'declined', 'rejected'].map((value) => (
              <option key={value} value={value}>{humanise(value)}</option>
            ))}
          </Select>
        )}
      </Field>
      <PreviewConfirm
        command="record_open_outcome"
        input={{
          cycle_id: cycleId,
          job_id: jobId,
          target_status: target as "offered",
          rows: selected.map(identifierRow),
          batch_key: batchKey,
          reason: target === "rejected" ? "" : undefined,
        }}
        title={`Record ${humanise(target).toLowerCase()} for ${selected.length}?`}
        confirmLabel="Record outcome"
        choices={target === "rejected" ? [{ name: "reason", label: "Reason", kind: "textarea", required: true }] : []}
        renderSummary={(summary) => (
          <BulkRows
            summary={summary as never}
            applyLabel={`Will be recorded ${humanise(target).toLowerCase()}`}
            resolveName={(row: BulkRow) => applicants.get(row.application_id ?? "")}
          />
        )}
        trigger={<Button variant="secondary" disabled={selected.length === 0}>Record outcome</Button>}
        onDone={onDone}
      />
    </div>
  );
}

/**
 * The name behind a row the command echoed back.
 *
 * A pasted roll comes back as the roll and needs nothing; a ticked row comes
 * back as the application id it was sent, and the list on screen is the only
 * place that knows whose it is.
 */
function applicantName(data: Data, row: BulkRow): string | undefined {
  return data.applications.find(
    (candidate) => candidate.application_id === row.application_id,
  )?.full_name;
}

function identifierRow(value: string): Record<string, string> {
  return value.includes("@") || !/^[0-9a-f-]{36}$/i.test(value)
    ? { identifier: value }
    : { application_id: value };
}
