import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { uploadVenueRows, type VenueUpload } from "@/api/client";
import { ExportButton } from "@/screens/analytics/ExportModal";
import { payload, type StaffJobBoardPayload } from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { BulkBar } from "@/components/BulkBar";
import { BulkRows, type BulkRow } from "@/components/BulkRows";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select } from "@/components/ui/input";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { cn } from "@/lib/cn";
import { formatZonedDateTime } from "@/lib/date";
import { newIdempotencyKey } from "@/lib/idempotency";
import { CreateExternalOffer } from "@/screens/offers/ExternalOffers";
import { reasonText } from "@/lib/reasons";
import { counted, humanise } from "@/lib/text";

type Board = StaffJobBoardPayload;
type Row = Board["columns"][number]["rows"][number];
type Operation = "advance" | "eliminate" | "waitlist" | "promote";

const LABEL: Record<Operation, string> = {
  advance: "Advance",
  eliminate: "Eliminate",
  waitlist: "Waitlist",
  promote: "Promote",
};

const COMMAND = {
  advance: "advance_applications",
  eliminate: "eliminate_applications",
  waitlist: "waitlist_applications",
  promote: "promote_waitlisted",
} as const;

const ALL_OPERATIONS = Object.keys(LABEL) as Operation[];
/** A job with no rounds has no round position to move, so only this remains. */
const ROUNDLESS_OPERATIONS: Operation[] = ["eliminate"];

/** The bucket a ticked row belongs to: a round id, or the round-less applicants. */
const UNROUTED = "unrouted";

/**
 * What the coordinator has selected.
 *
 * Ticked rows are held separately from pasted identifiers because the two are
 * constrained differently. A tick is scoped to one round at a time — advancing
 * round one and round two in a single batch is two different decisions wearing
 * one button — while a paste is deliberately scope-free: RND-2 promises a
 * pasted list is resolved by the *server*, which reports per row what it could
 * not match, so this screen must never quietly drop a token it did not
 * recognise.
 */
interface Selection {
  scope: string | null;
  ids: string[];
  pasted: string[];
}

const EMPTY: Selection = { scope: null, ids: [], pasted: [] };

function combined(selection: Selection): string[] {
  return [...selection.ids, ...selection.pasted];
}

/**
 * The ATS board (Behavior RND-1, RND-2, RND-3, RND-4).
 *
 * Columns are the job's rounds; a row sits in the round it is currently in.
 * The four pipeline operations run through `<BulkBar>` with a dry run first,
 * and the preview lists what will happen to each row *by name* rather than a
 * count, because RND-2's promise is that staff see the planned effect before
 * they commit it — including which pasted identifiers matched nothing.
 *
 * Attendance and venues are *round*-scoped rather than application-scoped, so
 * they live in their own panel with an explicit round picker: a mark or a slot
 * must never land on a round the coordinator was not looking at (the design review
 * §4.23). Every control's enabled state comes from the server's own answer on
 * the row — `actions.mark_attendance`, `actions.assign_venue` — never from the
 * client re-deriving the rule (§4.22).
 *
 * Finalization uses the same explicit round picker and preview contract. The
 * board receives each round's finalized marker and server-computed permission,
 * so a closed round is visible and cannot be offered for closing again. The
 * live offers panel is linked from the page header.
 */
export function JobBoard() {
  const { id = "" } = useParams();
  const screen = useScreen("staff/job/{id}/board", { params: { id } });
  const [selection, setSelection] = useState<Selection>(EMPTY);
  const [note, setNote] = useState<string | null>(null);
  const selected = useMemo(() => combined(selection), [selection]);
  const batchKey = useMemo(() => newIdempotencyKey(), [selected.join(",")]);

  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<Board>(screen.data);
  const frozen = data.cycle.archived || data.job.cancelled;
  const hasRounds = data.job.has_rounds;

  // Every row the board is rendering, by application id. This is what makes a
  // bulk button honest: the server already answered "can this row advance"
  // per row (the design review §4.22), so the button asks that answer rather than
  // re-deriving the rule and disagreeing with the command it triggers.
  const byId = new Map<string, Row>();
  for (const column of data.columns) for (const row of column.rows) byId.set(row.application_id, row);
  for (const row of data.unrouted) byId.set(row.application_id, row);
  for (const row of data.settled) byId.set(row.application_id, row);

  const scopeName = (scope: string) =>
    scope === UNROUTED
      ? "Applicants"
      : data.columns.find((column) => column.id === scope)?.name ?? "another round";

  /**
   * Move the tick selection into `scope`, dropping anything ticked elsewhere.
   *
   * One round at a time is the rule: the four operations act on where a row
   * sits, so a batch spanning two rounds asks one button to mean two things.
   * What was dropped is said out loud rather than silently discarded.
   */
  function retarget(scope: string, next: string[]) {
    const dropped =
      selection.scope !== null && selection.scope !== scope ? selection.ids.length : 0;
    setNote(
      dropped === 0
        ? null
        : `Selection is limited to one round at a time; ${dropped} from ` +
            `${scopeName(selection.scope!)} ${dropped === 1 ? "was" : "were"} cleared.`,
    );
    setSelection((current) =>
      next.length === 0
        ? { scope: null, ids: [], pasted: current.pasted }
        : { scope, ids: next, pasted: current.pasted },
    );
  }

  function toggleRow(scope: string, applicationId: string, checked: boolean) {
    const inScope = selection.scope === scope ? selection.ids : [];
    retarget(
      scope,
      checked
        ? [...inScope.filter((item) => item !== applicationId), applicationId]
        : inScope.filter((item) => item !== applicationId),
    );
  }

  function toggleAll(scope: string, rows: readonly Row[], checked: boolean) {
    retarget(scope, checked ? rows.map((row) => row.application_id) : []);
  }

  /** BulkBar only ever clears or appends; split what it hands back by shape. */
  function onBulkChange(next: string[]) {
    setNote(null);
    const ids = selection.ids.filter((value) => next.includes(value));
    setSelection({
      scope: ids.length > 0 ? selection.scope : null,
      ids,
      // Anything the board is not rendering is a pasted identifier, and the
      // server is what resolves it (RND-2).
      pasted: next.filter((value) => !byId.has(value)),
    });
  }

  const clear = () => {
    setSelection(EMPTY);
    setNote(null);
  };

  const operations = hasRounds ? ALL_OPERATIONS : ROUNDLESS_OPERATIONS;

  return (
    <>
      <PageHeader
        title={data.job.title}
        subtitle={
          hasRounds
            ? `${data.job.company} · ${data.counts.in_pipeline} in the pipeline of ${data.counts.total}`
            : `${data.job.company} · ${data.counts.unrouted} live of ${counted(data.counts.total, "applicant")}`
        }
        actions={
          <div className="flex gap-gap-md">
            <ExportButton
              cycleId={data.cycle.id}
              jobId={data.job.id}
              kind="job_applications"
              label="Export students"
              columns={data.export_columns}
              preset={data.export_preset}
              cohorts={[
                { value: "applicants", label: "Applicants (before round 1)" },
                ...data.rounds.map((round) => ({ value: `round-${round.id}`, label: `${round.ord} · ${round.name}`, roundId: round.id })),
                { value: "offers", label: "Everyone issued an offer" },
              ]}
            />
            <Button variant={hasRounds ? "secondary" : "primary"} asChild>
              <Link to={`/staff/jobs/${data.job.id}/offers`}>Offers</Link>
            </Button>
          </div>
        }
      />

      {!hasRounds ? (
        <div className="rounded border border-info-border bg-info-subtle p-container-padding text-body-md text-foreground">
          This job runs no rounds: an open-cycle job goes applied → offered → accepted.
          Extend or record offers on the Offers screen.
        </div>
      ) : null}

      {frozen ? (
        <div className="rounded border border-warning-border bg-warning-subtle p-container-padding text-body-md text-foreground">
          This board is read-only: the {data.cycle.archived ? "cycle is archived" : "job is cancelled"}.
        </div>
      ) : (
        <div className="flex flex-col gap-gap-md">
          <BulkBar
            selected={selected}
            onChange={onBulkChange}
            identifierLabel="roll numbers or emails"
            actions={
              <div className="flex flex-wrap items-center gap-gap-md">
                {operations.map((operation) => (
                  <BoardAction
                    key={operation}
                    operation={operation}
                    cycleId={data.cycle.id}
                    jobId={data.job.id}
                    batchKey={batchKey}
                    selection={selection}
                    byId={byId}
                    onDone={clear}
                  />
                ))}
              </div>
            }
          />
          {note ? <p className="text-body-sm text-muted-foreground">{note}</p> : null}
        </div>
      )}

      {frozen || data.rounds.length === 0 ? null : (
        <RoundOperations
          rounds={data.rounds}
          cycleId={data.cycle.id}
          jobId={data.job.id}
          selected={selected}
          onDone={clear}
        />
      )}

      <div className="flex flex-col gap-gap-lg">
        {data.unrouted.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-gap-md">
                {frozen ? null : (
                  <SelectAll
                    label="every applicant"
                    rows={data.unrouted}
                    selectedIds={selection.scope === UNROUTED ? selection.ids : []}
                    onChange={(checked) => toggleAll(UNROUTED, data.unrouted, checked)}
                  />
                )}
                Applicants{" "}
                <span className="text-muted-foreground">({data.unrouted.length})</span>
              </CardTitle>
              <span className="text-body-sm text-muted-foreground">
                {hasRounds ? "Applied, holding no round position" : "Awaiting an offer decision"}
              </span>
            </CardHeader>
            <CardBody>
              <ul className="flex flex-col gap-gap-md">
                {data.unrouted.map((row) => (
                  <BoardRow
                    key={row.application_id}
                    row={row}
                    cycleId={data.cycle.id}
                    jobId={data.job.id}
                    job={data.job}
                    selected={
                      selection.scope === UNROUTED && selection.ids.includes(row.application_id)
                    }
                    frozen={frozen}
                    onToggle={(checked) => toggleRow(UNROUTED, row.application_id, checked)}
                  />
                ))}
              </ul>
            </CardBody>
          </Card>
        ) : null}

        {data.columns.length === 0 && data.unrouted.length === 0 ? (
          <Card>
            <CardBody>
              <EmptyState message="No pipeline rounds or applicants are available for this job." />
            </CardBody>
          </Card>
        ) : null}
        {data.columns.map((column) => {
          const currentRows = column.rows.filter((row) => row.is_current_round !== false);
          return (
          <Card key={column.id}>
            <CardHeader>
              <CardTitle className="flex items-center gap-gap-md">
                {frozen || currentRows.length === 0 ? null : (
                  <SelectAll
                    label={`everyone in ${column.name}`}
                    rows={currentRows}
                    selectedIds={selection.scope === column.id ? selection.ids : []}
                    onChange={(checked) => toggleAll(column.id, currentRows, checked)}
                  />
                )}
                {column.ord}. {column.name}{" "}
                <span className="text-muted-foreground">({column.count})</span>
              </CardTitle>
              <RoundFinalizedState round={column} />
            </CardHeader>
            <CardBody>
              {column.rows.length === 0 ? (
                <EmptyState message="Nobody has reached this round." />
              ) : (
                <ul className="flex flex-col gap-gap-md">
                  {column.rows.map((row) => (
                    <BoardRow
                      key={row.application_id}
                      row={row}
                      cycleId={data.cycle.id}
                      jobId={data.job.id}
                      job={data.job}
                      selected={
                        selection.scope === column.id &&
                        selection.ids.includes(row.application_id)
                      }
                      frozen={frozen || row.is_current_round === false}
                      onToggle={(checked) => toggleRow(column.id, row.application_id, checked)}
                    />
                  ))}
                </ul>
              )}
            </CardBody>
          </Card>
          );
        })}

        {!hasRounds && data.settled.length > 0 ? (
          <Card>
            <CardHeader>
              <CardTitle>
                Out of the pipeline{" "}
                <span className="text-muted-foreground">({data.settled.length})</span>
              </CardTitle>
            </CardHeader>
            <CardBody>
              <ul className="flex flex-col gap-gap-md">
                {data.settled.map((row) => (
                  <BoardRow
                    key={row.application_id}
                    row={row}
                    cycleId={data.cycle.id}
                    jobId={data.job.id}
                    job={data.job}
                    selected={false}
                    frozen
                  />
                ))}
              </ul>
            </CardBody>
          </Card>
        ) : null}
      </div>
    </>
  );
}

/**
 * A whole round's worth of rows in one tick.
 *
 * Indeterminate is a DOM property rather than an attribute, so it is applied
 * through the ref the way `components/ui/checkbox` documents.
 */
function SelectAll({
  label,
  rows,
  selectedIds,
  onChange,
}: {
  label: string;
  rows: readonly Row[];
  selectedIds: readonly string[];
  onChange: (checked: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const picked = rows.filter((row) => selectedIds.includes(row.application_id)).length;
  const all = picked === rows.length && rows.length > 0;
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = picked > 0 && !all;
  }, [picked, all]);
  return (
    <Checkbox
      ref={ref}
      checked={all}
      onChange={(event) => onChange(event.target.checked)}
      aria-label={`Select ${label}`}
    />
  );
}

function BoardRow({
  row,
  cycleId,
  jobId,
  job,
  selected,
  frozen,
  onToggle,
}: {
  row: Row;
  cycleId: string;
  jobId: string;
  job: Board["job"];
  selected: boolean;
  frozen: boolean;
  onToggle?: (checked: boolean) => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-gap-md rounded border border-border p-gap-md">
      {frozen || !onToggle ? null : (
        <Checkbox
          checked={selected}
          onChange={(event) => onToggle(event.target.checked)}
          aria-label={`Select ${row.full_name}`}
        />
      )}
      <span className="min-w-0 flex-1">
        <span className="text-body-md text-foreground">{row.full_name}</span>
        {row.roll_number ? (
          <span className="ml-gap-md text-body-sm text-muted-foreground">{row.roll_number}</span>
        ) : null}
        <SlotLine row={row} />
      </span>
      {row.result ? <StatusChip domain="round" value={row.result} /> : null}
      {row.is_current_round !== false ? (
        <AttendanceChip row={row} cycleId={cycleId} jobId={jobId} />
      ) : row.attendance && row.attendance !== "pending" ? (
        <StatusChip domain="attendance" value={row.attendance} />
      ) : null}
      <StatusChip domain="application" value={row.status} />
      {job.outcome === "internship" ? (
        <CreateExternalOffer
          enrollments={[]}
          companies={[]}
          preset={{
            enrollment_id: row.enrollment_id,
            company_id: job.company_id,
            source_application_id: row.application_id,
            student: row.full_name,
            company: job.company,
          }}
          trigger={<Button variant="secondary" size="sm">Record PPO</Button>}
        />
      ) : null}
    </li>
  );
}

/** The slot this student has, and whether it is theirs alone (RND-1, RND-4). */
function SlotLine({ row }: { row: Row }) {
  if (!row.venue && !row.scheduled_at) return null;
  return (
    <span className="mt-gap-tight block text-body-sm text-muted-foreground">
      {[row.venue, row.scheduled_at ? formatSlot(row.scheduled_at) : null]
        .filter(Boolean)
        .join(" · ")}
      {row.slot_is_override ? null : " (round default)"}
      {row.slot_is_override && !row.slot_notified_at ? " — not yet published" : null}
    </span>
  );
}

function formatSlot(iso: string): string {
  return formatZonedDateTime(iso);
}

function RoundFinalizedState({
  round,
}: {
  round: Pick<Board["rounds"][number], "finalized_at" | "finalized_by">;
}) {
  if (!round.finalized_at) {
    return <span className="text-body-sm text-muted-foreground">Open</span>;
  }
  return (
    <span className="text-body-sm text-muted-foreground">
      Finalized {formatSlot(round.finalized_at)}
      {round.finalized_by?.name ? ` by ${round.finalized_by.name}` : ""}
    </span>
  );
}

/**
 * Attendance, said outright.
 *
 * This was one chip that cycled pending → present → absent → excused, so
 * marking a room absent meant clicking every name twice and no control
 * anywhere said "absent". RND-3 makes absence consequential — finalisation
 * rejects the absentee and may award a strike — which is not a state to arrive
 * at by counting clicks.
 *
 * Each button sends the value it names together with the value it was
 * rendering, so a second coordinator acting on the same row is refused as
 * `stale_view` rather than silently overwriting (the design review §4.23). Whether the
 * control is live at all is the server's answer on the row, never a rule
 * re-derived here.
 */
const ATTENDANCE_MARKS = [
  { value: "present", label: "Present" },
  { value: "absent", label: "Absent" },
  { value: "excused", label: "Excused" },
  { value: "pending", label: "Not marked" },
] as const;

function AttendanceChip({ row, cycleId, jobId }: { row: Row; cycleId: string; jobId: string }) {
  const mark = useCommand("mark_attendance");
  const current = row.attendance ?? "pending";
  const permission = row.actions["mark_attendance"];
  const allowed = permission?.allowed === true && row.round !== null;

  if (!allowed) {
    return (
      <span title={permission?.human ?? undefined}>
        <StatusChip domain="attendance" value={current} />
      </span>
    );
  }

  return (
    <div className="flex items-center gap-gap-tight">
      <StatusChip domain="attendance" value={current} />
      <div role="group" aria-label={`Attendance for ${row.full_name}`} className="flex gap-gap-tight">
        {ATTENDANCE_MARKS.filter((mark) => mark.value !== current).map((option) => (
          <button
            key={option.value}
            type="button"
            disabled={mark.isPending}
            title={`Mark ${option.label.toLowerCase()}`}
            aria-label={`Mark ${row.full_name} ${option.label.toLowerCase()}`}
            className={cn(
              "rounded border border-border px-gap-tight py-px text-body-sm text-muted-foreground",
              "transition-colors hover:bg-muted hover:text-foreground",
              "focus-visible:outline-2 focus-visible:outline-offset-2",
              "focus-visible:outline-brand disabled:opacity-60",
            )}
            onClick={() =>
              mark.mutate({
                input: {
                  cycle_id: cycleId,
                  job_id: jobId,
                  // The board states every input this control needs (§4.22):
                  // the round comes from the row, never from a second query.
                  round_id: row.round?.id ?? "",
                  application_id: row.application_id,
                  attendance: option.value,
                  expected_attendance: current,
                } as never,
              })
            }
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}


/**
 * Whether this operation can do anything to what is selected, and why not.
 *
 * The answer comes from the rows the board is already rendering, each carrying
 * the server's own verdict from `plan_row` — the same function the command
 * runs. Pasted identifiers are unresolved by design (RND-2 leaves matching to
 * the server), so a selection containing one never disables a button: the
 * preview is where the coordinator finds out what it matched.
 */
function actionState(
  operation: Operation,
  selection: Selection,
  byId: ReadonlyMap<string, Row>,
): { enabled: boolean; title?: string } {
  if (selection.ids.length === 0 && selection.pasted.length === 0) return { enabled: false };
  if (selection.pasted.length > 0) return { enabled: true };
  const known = selection.ids.map((id) => byId.get(id)).filter((row): row is Row => !!row);
  if (known.length < selection.ids.length) return { enabled: true };
  if (known.some((row) => row.actions[operation]?.allowed === true)) return { enabled: true };
  const blocked = known[0]?.actions[operation];
  return {
    enabled: false,
    ...(blocked?.reason
      ? { title: reasonText(blocked.reason, blocked.human ?? undefined) }
      : {}),
  };
}

function BoardAction({
  operation,
  cycleId,
  jobId,
  batchKey,
  selection,
  byId,
  onDone,
}: {
  operation: Operation;
  cycleId: string;
  jobId: string;
  batchKey: string;
  selection: Selection;
  byId: ReadonlyMap<string, Row>;
  onDone: () => void;
}) {
  const selected = combined(selection);
  const state = actionState(operation, selection, byId);
  // A ticked row is an application id, a pasted one is whatever was typed. The
  // server resolves both and reports what it could not match, so the client
  // never guesses which is which.
  const rows = selected.map(identifierRow);
  const input = {
    cycle_id: cycleId,
    job_id: jobId,
    batch_key: batchKey,
    rows,
    ...(operation === "eliminate" ? { reason: "" } : {}),
  };

  return (
    <PreviewConfirm
      command={COMMAND[operation]}
      input={input as never}
      title={`${LABEL[operation]} ${selected.length} applicant${selected.length === 1 ? "" : "s"}?`}
      confirmLabel={LABEL[operation]}
      destructive={operation === "eliminate"}
      choices={
        operation === "eliminate"
          ? [
              {
                name: "reason",
                label: "Reason",
                kind: "textarea",
                required: true,
                hint: "Recorded on every event and sent to each student.",
              },
            ]
          : []
      }
      renderSummary={(summary) => (
        <BulkRows
          summary={summary as never}
          applyLabel="Will move"
          describe={(row: PlannedRow) =>
            ` → ${row.to_round ?? (row.to_status ? humanise(row.to_status).toLowerCase() : "")}`
          }
        />
      )}
      trigger={
        <Button
          variant={operation === "eliminate" ? "ghost" : "secondary"}
          disabled={!state.enabled}
          title={state.title}
        >
          {LABEL[operation]}
        </Button>
      }
      onDone={onDone}
    />
  );
}

/** What the four pipeline operations add to the shared bulk row. */
interface PlannedRow extends BulkRow {
  to_status?: string | null;
  to_round?: string | null;
}

interface FinalizationRow {
  application_id: string;
  full_name: string;
  roll_number: string | null;
  attendance_before: string | null;
  attendance_after: string | null;
  to_status: string;
  reason: string;
  earns_strike: boolean;
  outcome: "finalized" | "untouched";
}

/** Every consequence the finalization command reports, including strikes. */
function FinalizationPlan({
  summary,
}: {
  summary: {
    round_name: string;
    rows: FinalizationRow[];
    finalized: number;
    strikes: number;
    penalties: number;
  };
}) {
  const rows = summary.rows ?? [];
  const changing = rows.filter((row) => row.outcome === "finalized");
  const untouched = rows.filter((row) => row.outcome === "untouched");
  return (
    <div className="flex flex-col gap-gap-lg">
      <p className="text-body-md text-foreground">
        {summary.finalized} finalized · {summary.strikes}{" "}
        {summary.strikes === 1 ? "strike" : "strikes"} · {summary.penalties}{" "}
        {summary.penalties === 1 ? "penalty" : "penalties"}
      </p>
      <FinalizationRows title="Will finalize" rows={changing} />
      {untouched.length > 0 ? (
        <FinalizationRows title="Will remain untouched" rows={untouched} muted />
      ) : null}
    </div>
  );
}

function FinalizationRows({
  title,
  rows,
  muted = false,
}: {
  title: string;
  rows: FinalizationRow[];
  muted?: boolean;
}) {
  return (
    <section>
      <p className="text-label-caps uppercase text-muted-foreground">
        {title} ({rows.length})
      </p>
      {rows.length === 0 ? (
        <p className="mt-gap-tight text-body-sm text-muted-foreground">Nobody.</p>
      ) : (
        <ul className="mt-gap-tight flex flex-col gap-gap-tight">
          {rows.map((row) => (
            <li
              key={row.application_id}
              className={muted ? "text-body-sm text-muted-foreground" : "text-body-md text-foreground"}
            >
              {row.full_name}
              {row.roll_number ? ` (${row.roll_number})` : ""} — attendance{" "}
              {row.attendance_before ?? "pending"} → {row.attendance_after ?? "pending"};{" "}
              {humanise(row.to_status)} ({humanise(row.reason).toLowerCase()})
              {row.earns_strike ? (
                <strong className="ml-gap-tight text-danger">· will earn a strike</strong>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/**
 * Attendance and venues, which belong to a *round* rather than to a pipeline.
 *
 * The round picker is explicit and required: advancing an application is a
 * fact about the application, but marking someone present is a fact about the
 * room they were in, and a paste of fifty rolls landing on whichever round each
 * row happened to be sitting in is exactly the accident §4.23 exists to
 * prevent. Both actions read the same `<BulkBar>` selection as the pipeline
 * operations — a ticked row or a pasted roll — and the server reports, per row,
 * which of them were not in the round after all.
 */
function RoundOperations({
  rounds,
  cycleId,
  jobId,
  selected,
  onDone,
}: {
  rounds: Board["rounds"];
  cycleId: string;
  jobId: string;
  selected: readonly string[];
  onDone: () => void;
}) {
  const [roundId, setRoundId] = useState(rounds[0]?.id ?? "");
  const [venue, setVenue] = useState("");
  const [time, setTime] = useState("");
  const [upload, setUpload] = useState<VenueUpload | null>(null);
  const [uploadError, setUploadError] = useState<unknown>(null);
  const batchKey = useMemo(
    () => newIdempotencyKey(),
    [roundId, selected.join(","), venue, time, upload],
  );

  const selectedRound = rounds.find((round) => round.id === roundId) ?? null;
  const finalizePermission = selectedRound?.actions.finalize;
  const slotRows = upload
    ? upload.rows.map((row) => ({
        identifier: row.identifier,
        venue: row.venue,
        time: row.time,
      }))
    : selected.map((value) => ({ ...identifierRow(value), venue, time }));
  const canPublish = slotRows.length > 0 && (upload !== null || venue !== "" || time !== "");

  async function onFile(file: File | undefined) {
    if (!file) return;
    setUploadError(null);
    try {
      setUpload(await uploadVenueRows(file));
    } catch (error) {
      setUpload(null);
      setUploadError(error);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>This round</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        <div className="max-w-xs">
          <Field label="Round" required hint="Attendance and venues are recorded per round.">
            {(field) => (
              <Select
                {...field}
                value={roundId}
                onChange={(event) => setRoundId(event.target.value)}
              >
                {rounds.map((round) => (
                  <option key={round.id} value={round.id}>
                    {round.ord} · {round.name}{round.finalized_at ? " — finalized" : ""}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-gap-md">
          <PreviewConfirm
            command="finalize_round"
            input={
              {
                cycle_id: cycleId,
                job_id: jobId,
                round_id: roundId,
              } as never
            }
            title={`Finalize ${selectedRound?.name ?? "round"}?`}
            description="Pending and absent applicants are rejected; absences may also award strikes. Present and waitlisted applicants stay untouched."
            confirmLabel="Finalize round"
            destructive
            renderSummary={(summary) => <FinalizationPlan summary={summary as never} />}
            trigger={
              <Button
                variant="secondary"
                disabled={roundId === "" || finalizePermission?.allowed !== true}
                title={finalizePermission?.human ?? undefined}
              >
                Finalize round
              </Button>
            }
          />
          {selectedRound?.finalized_at ? (
            <span className="text-body-sm text-muted-foreground">
              Closed {formatSlot(selectedRound.finalized_at)}
              {selectedRound.finalized_by?.name
                ? ` by ${selectedRound.finalized_by.name}`
                : ""}
            </span>
          ) : (
            <span className="text-body-sm text-muted-foreground">
              Preview every affected applicant before closing this round.
            </span>
          )}
        </div>

        <div className="flex flex-wrap items-center gap-gap-md border-t border-border pt-gap-lg">
          <PreviewConfirm
            command="bulk_mark_present"
            input={
              {
                cycle_id: cycleId,
                job_id: jobId,
                round_id: roundId,
                batch_key: batchKey,
                rows: selected.map(identifierRow),
              } as never
            }
            title={`Mark ${selected.length} present?`}
            description="Only rows still pending are flipped; anything already marked is left alone."
            confirmLabel="Mark present"
            renderSummary={(summary) => (
              <BulkRows summary={summary as never} applyLabel="Will mark present" />
            )}
            trigger={
              <Button variant="secondary" disabled={selected.length === 0 || roundId === ""}>
                Mark present
              </Button>
            }
            onDone={onDone}
          />
          <PreviewConfirm
            command="bulk_mark_absent"
            input={{ cycle_id: cycleId, job_id: jobId, round_id: roundId, batch_key: batchKey, rows: selected.map(identifierRow) } as never}
            title={`Mark ${selected.length} absent?`}
            description="Only rows still pending are marked absent; existing attendance is preserved."
            confirmLabel="Mark absent"
            destructive
            renderSummary={(summary) => (
              <BulkRows summary={summary as never} applyLabel="Will mark absent" />
            )}
            trigger={<Button variant="secondary" disabled={selected.length === 0 || roundId === ""}>Mark absent</Button>}
            onDone={onDone}
          />
          <span className="text-body-sm text-muted-foreground">
            Paste the sheet from the room into the selection above, or tick rows.
          </span>
        </div>

        <div className="flex flex-col gap-gap-md border-t border-border pt-gap-lg">
          <p className="text-label-caps uppercase text-muted-foreground">Venue &amp; timing</p>
          <div className="flex flex-wrap items-end gap-gap-md">
            <Field label="Venue" hint="Left blank, each row keeps the venue it has.">
              {(field) => (
                <Input
                  {...field}
                  value={venue}
                  disabled={upload !== null}
                  placeholder="AB 5 / 204"
                  onChange={(event) => setVenue(event.target.value)}
                />
              )}
            </Field>
            <Field label="Time" hint="2026-03-14 09:30 or 14-03-2026 09:30, in IST.">
              {(field) => (
                <Input
                  {...field}
                  value={time}
                  disabled={upload !== null}
                  placeholder="2026-03-14 09:30"
                  onChange={(event) => setTime(event.target.value)}
                />
              )}
            </Field>
            <Field label="Or upload a sheet" hint="CSV or XLSX: identifier, venue, time.">
              {(field) => (
                <Input
                  {...field}
                  type="file"
                  accept=".csv,.xlsx"
                  onChange={(event) => void onFile(event.target.files?.[0])}
                />
              )}
            </Field>
            <PreviewConfirm
              command="assign_venue_timing"
              input={
                {
                  cycle_id: cycleId,
                  job_id: jobId,
                  round_id: roundId,
                  batch_key: batchKey,
                  rows: slotRows,
                } as never
              }
              title={`Publish a slot for ${slotRows.length} applicant${slotRows.length === 1 ? "" : "s"}?`}
              description="Publishing emails each student; anyone already told is emailed an update."
              confirmLabel="Publish"
              renderSummary={(summary) => <PublishedSlots summary={summary as never} />}
              trigger={
                <Button variant="secondary" disabled={!canPublish || roundId === ""}>
                  Publish
                </Button>
              }
              onDone={() => {
                setUpload(null);
                setVenue("");
                setTime("");
                onDone();
              }}
            />
          </div>

          {uploadError ? (
            <ErrorState error={uploadError} title="Could not read the venue sheet" />
          ) : null}
          {upload ? <UploadReport upload={upload} onClear={() => setUpload(null)} /> : null}
        </div>
      </CardBody>
    </Card>
  );
}

/**
 * What the parser made of the file, before any of it is sent.
 *
 * Rows it could not read are listed one by one with the row number and the
 * reason, for the same reason unmatched identifiers are: a spreadsheet with
 * three bad times is a request to be shown the three.
 */
function UploadReport({ upload, onClear }: { upload: VenueUpload; onClear: () => void }) {
  return (
    <div className="flex flex-col gap-gap-md rounded border border-border bg-muted p-gap-lg">
      <div className="flex items-center justify-between gap-gap-md">
        <p className="text-body-md text-foreground">
          {upload.rows.length} row{upload.rows.length === 1 ? "" : "s"} read from the file
        </p>
        <Button variant="ghost" onClick={onClear}>
          Clear
        </Button>
      </div>
      {upload.errors.length > 0 ? (
        <div>
          <p className="text-label-caps uppercase text-danger">
            Could not read ({upload.errors.length})
          </p>
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {upload.errors.map((problem, index) => (
              <li key={index} className="text-body-sm text-foreground">
                {problem.row_number === null ? "File" : `Row ${problem.row_number}`} —{" "}
                {problem.human}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

interface PublishedSlot {
  identifier: string;
  full_name: string | null;
  status: string;
  reason: string | null;
  human: string | null;
  venue: string | null;
  scheduled_at: string | null;
  is_update: boolean | null;
}

/** The per-row plan for a publish: who gets what, who is told again, who is already right. */
function PublishedSlots({ summary }: { summary: { rows: PublishedSlot[] } }) {
  const rows = summary.rows ?? [];
  const publishing = rows.filter((row) => row.status === "ok");
  // A row the sheet does not move is the ordinary case when a corrected sheet
  // is re-uploaded (the design review §4.46). It publishes nothing and mails nobody,
  // which is not a problem and must not be shown as one.
  const unchanged = rows.filter((row) => row.status === "unchanged");
  const problems = rows.filter(
    (row) => row.status !== "ok" && row.status !== "unchanged",
  );

  return (
    <div className="flex flex-col gap-gap-lg">
      <section>
        <p className="text-label-caps uppercase text-muted-foreground">
          Will publish ({publishing.length})
        </p>
        {publishing.length === 0 ? (
          <p className="mt-gap-tight text-body-sm text-muted-foreground">Nobody.</p>
        ) : (
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {publishing.map((row) => (
              <li key={row.identifier} className="text-body-md text-foreground">
                {row.full_name ?? row.identifier}
                {" → "}
                <span className="text-muted-foreground">
                  {[row.venue, row.scheduled_at ? formatSlot(row.scheduled_at) : null]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
                {row.is_update ? (
                  <span className="text-warning"> · update</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>
      {unchanged.length > 0 ? (
        <section>
          <p className="text-label-caps uppercase text-muted-foreground">
            Already up to date ({unchanged.length})
          </p>
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {unchanged.map((row) => (
              <li key={row.identifier} className="text-body-sm text-muted-foreground">
                {row.full_name ?? row.identifier}
                {" → "}
                {[row.venue, row.scheduled_at ? formatSlot(row.scheduled_at) : null]
                  .filter(Boolean)
                  .join(" · ")}
                {" · unchanged, will not be emailed again"}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {problems.length > 0 ? (
        <section>
          <p className="text-label-caps uppercase text-danger">
            Will not publish ({problems.length})
          </p>
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {problems.map((row) => (
              <li key={row.identifier} className="text-body-sm text-foreground">
                {row.full_name ?? row.identifier} —{" "}
                {reasonText(row.reason ?? "", row.human ?? undefined)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

/** A ticked row is an application id; a pasted one is whatever was typed. */
function identifierRow(value: string): { application_id: string } | { identifier: string } {
  return /^[0-9a-f-]{36}$/i.test(value) ? { application_id: value } : { identifier: value };
}
