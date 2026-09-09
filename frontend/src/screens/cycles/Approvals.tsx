import { ArrowLeft, Inbox } from "lucide-react";
import { useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { Link, useParams } from "react-router-dom";

import { payload, type ApprovalsPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { BulkBar } from "@/components/BulkBar";
import { BulkRows, type BulkRow } from "@/components/BulkRows";
import { MembershipExit } from "@/components/MembershipExit";
import { OutcomeTag } from "@/components/OutcomeTag";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/input";
import { StatusChip } from "@/components/ui/statusChip";
import { humanise } from "@/lib/text";
import { DataTable, type Column } from "@/components/ui/table";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";

type Row = ApprovalsPayload["rows"][number];

/**
 * The membership approval queue (Behavior CYC-3, LLD §11.3).
 *
 * Approval is the bulk path and runs through `<BulkBar>`; rejection is not,
 * because CYC-3 requires a reason per membership and a reason pasted once for
 * fifty students is not a reason. So the toolbar approves a selection and the
 * row rejects one person.
 *
 * `BulkBar` lets identifiers be pasted as well as ticked. A ticked row is a
 * membership id; a pasted one is a roll number or an institute email, which the
 * command resolves itself — asking a coordinator to paste membership ids they
 * have no way to read off the screen is asking for nothing they can supply.
 * Either way an identifier that matches nothing comes back from the server as
 * `unmatched_identifier` in the result rows — the client never claims a paste
 * resolved.
 */
export function Approvals() {
  const { id = "" } = useParams();
  const [status, setStatus] = useState("pending");
  const screen = useScreen("staff/cycle/{id}/approvals", {
    params: { id },
    query: { status },
  });
  const [selected, setSelected] = useState<string[]>([]);
  // One key per selection: a retry of the same intent replays rather than
  // re-approving, and a *different* selection is a different batch (RND-2).
  const batchKey = useMemo(
    () => `approvals-${id}-${[...selected].sort().join(",")}`,
    [id, selected],
  );

  if (screen.isPending) return <ScreenSkeleton variant="table" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<ApprovalsPayload>(screen.data);
  const rows = data.rows;
  const pending = status === "pending";
  const allSelected = rows.length > 0 && rows.every((row) => selected.includes(row.membership_id));

  const columns: Column<Row>[] = [
    ...(pending
      ? [selectColumn(rows, selected, setSelected, allSelected)]
      : []),
    {
      key: "student",
      header: "Student",
      cell: (row) => (
        <div className="flex flex-col">
          <span className="text-foreground">{row.full_name}</span>
          <span className="text-body-sm text-muted-foreground">{row.email}</span>
        </div>
      ),
    },
    {
      key: "roll",
      header: "Roll",
      numeric: true,
      cell: (row) => row.roll_number ?? <span className="text-muted-foreground">—</span>,
    },
    {
      key: "resume",
      header: "Resume",
      cell: (row) =>
        row.resume ? (
          <a
            href={row.resume.drive_url}
            target="_blank"
            rel="noreferrer"
            className="text-accent hover:underline"
          >
            {row.resume.label}
          </a>
        ) : (
          <span className="text-muted-foreground">None</span>
        ),
    },
    {
      key: "status",
      header: "Status",
      cell: (row) => <StatusChip domain="membership" value={row.status} />,
    },
    {
      key: "outcome",
      header: "Outcome",
      cell: (row) => (
        <OutcomeTag
          cycleId={id}
          membershipId={row.membership_id}
          subject={`${row.full_name}'s outcome`}
          current={row.outcome_tag}
          permission={row.actions.set_outcome_tag}
        />
      ),
    },
    {
      key: "actions",
      header: <span className="sr-only">Actions</span>,
      numeric: true,
      // A pending row is a decision; every other row is a membership that can
      // be taken out of the cycle or put back (CYC-3.7, 3.8).
      cell: (row) =>
        row.status === "pending" ? (
          <PreviewConfirm
            command="reject_membership"
            input={{ cycle_id: id, membership_id: row.membership_id, reason: "" }}
            title={`Reject ${row.full_name}?`}
            description="They can correct their profile and request again."
            confirmLabel="Reject request"
            destructive
            choices={[
              {
                name: "reason",
                label: "Reason",
                kind: "textarea",
                required: true,
                hint: "Shown to the student, so it should say what to fix.",
              },
            ]}
            trigger={
              <Button variant="destructive-ghost" size="sm">
                Reject
              </Button>
            }
          />
        ) : (
          <MembershipExit
            cycleId={id}
            membershipId={row.membership_id}
            fullName={row.full_name}
            status={row.status}
            actions={row.actions}
          />
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
            <ArrowLeft className="h-3 w-3" /> {data.cycle.name}
          </Link>
        }
        title="Approvals"
        subtitle={
          pending
            ? `${rows.length} request${rows.length === 1 ? "" : "s"} waiting on a decision.`
            : `${rows.length} ${humanise(status).toLowerCase()} member${rows.length === 1 ? "" : "s"} in this cycle.`
        }
        actions={
          <Field label="Membership status">
            {(field) => (
              <Select
                {...field}
                value={status}
                onChange={(event) => {
                  setStatus(event.target.value);
                  // A selection made against one list means nothing in
                  // another: the ids would still submit, silently approving
                  // rows the coordinator can no longer see.
                  setSelected([]);
                }}
              >
                {data.statuses.map((item) => (
                  <option key={item} value={item}>
                    {humanise(item)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        }
      />

      {pending ? (
      <BulkBar
        selected={selected}
        onChange={setSelected}
        identifierLabel="roll numbers or emails"
        actions={
          <PreviewConfirm
            command="approve_memberships"
            input={{
              cycle_id: id,
              batch_key: batchKey,
              rows: selected.map(identifierRow),
            }}
            title={`Approve ${selected.length} request${selected.length === 1 ? "" : "s"}?`}
            description="Approved students become active members and can start applying."
            confirmLabel="Approve"
            renderSummary={(summary) => (
              <BulkRows
                summary={summary as never}
                applyLabel="Will approve"
                // A ticked row reports the membership id it was sent, which is
                // not a thing a coordinator can recognise. The queue in front
                // of them is where the name is.
                resolveName={(row: BulkRow) =>
                  rows.find(
                    (candidate) =>
                      candidate.membership_id === (row.membership_id ?? row.identifier),
                  )?.full_name
                }
              />
            )}
            trigger={
              <Button variant="primary" disabled={selected.length === 0}>
                Approve selected
              </Button>
            }
            onDone={() => setSelected([])}
          />
        }
      />
      ) : null}

      <Card>
        <CardHeader>
          <CardTitle>{pending ? "Pending requests" : `${humanise(status)} members`}</CardTitle>
        </CardHeader>
        <DataTable
          columns={columns}
          rows={rows}
          rowKey={(row) => row.membership_id}
          isSelected={(row) => selected.includes(row.membership_id)}
          empty={
            <CardBody>
              <EmptyState
                icon={<Inbox className="h-8 w-8" />}
                message={
                  pending
                    ? "Nothing waiting. Every request in this cycle has been decided."
                    : `No ${humanise(status).toLowerCase()} memberships in this cycle.`
                }
              />
            </CardBody>
          }
        />
      </Card>
    </>
  );
}

/** A ticked row is a membership id; a pasted one is whatever was typed. */
function identifierRow(value: string): { membership_id: string } | { identifier: string } {
  return /^[0-9a-f-]{36}$/i.test(value) ? { membership_id: value } : { identifier: value };
}

/** The tick column, which only the pending queue has anything to do with. */
function selectColumn(
  rows: Row[],
  selected: string[],
  setSelected: Dispatch<SetStateAction<string[]>>,
  allSelected: boolean,
): Column<Row> {
  return {
    key: "select",
    width: "48px",
    header: (
      <Checkbox
        aria-label="Select every request"
        checked={allSelected}
        onChange={(event) =>
          setSelected(event.target.checked ? rows.map((row) => row.membership_id) : [])
        }
      />
    ),
    cell: (row) => (
      <Checkbox
        aria-label={`Select ${row.full_name}`}
        checked={selected.includes(row.membership_id)}
        onChange={(event) =>
          setSelected((prev) =>
            event.target.checked
              ? [...prev, row.membership_id]
              : prev.filter((value) => value !== row.membership_id),
          )
        }
      />
    ),
  };
}
