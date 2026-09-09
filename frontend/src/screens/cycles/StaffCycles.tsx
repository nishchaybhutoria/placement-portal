import { CalendarRange, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { payload, type StaffCyclesPayload } from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select, Textarea } from "@/components/ui/input";
import { DataTable, type Column } from "@/components/ui/table";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states";
import { counted, humanise } from "@/lib/text";

type Cycle = StaffCyclesPayload["cycles"][number];

/** Every cycle with the counts staff triage from (LLD §11.3 `staff/cycles`). */
export function StaffCycles() {
  const [includeArchived, setIncludeArchived] = useState(false);
  const [kind, setKind] = useState("");
  const screen = useScreen("staff/cycles", {
    query: { include_archived: includeArchived, kind: kind || undefined },
  });
  const [creating, setCreating] = useState(false);
  const createPermission = screen.data
    ? payload<StaffCyclesPayload>(screen.data).actions.create
    : { allowed: false, human: null };

  const columns: Column<Cycle>[] = [
    {
      key: "name",
      header: "Cycle",
      cell: (cycle) => (
        <div className="flex flex-col">
          <Link
            to={`/staff/cycles/${cycle.id}`}
            className="font-medium text-accent hover:underline"
          >
            {cycle.name}
          </Link>
          {cycle.description ? (
            <span className="text-body-sm text-muted-foreground">{cycle.description}</span>
          ) : null}
        </div>
      ),
    },
    { key: "kind", header: "Kind", cell: (cycle) => humanise(cycle.kind) },
    {
      key: "state",
      header: "State",
      cell: (cycle) =>
        cycle.archived_at ? (
          <span className="text-muted-foreground">Archived</span>
        ) : cycle.is_active ? (
          "Active"
        ) : (
          <span className="text-muted-foreground">Inactive</span>
        ),
    },
    { key: "pending", header: "Pending", numeric: true, cell: (cycle) => cycle.pending_count },
    { key: "active", header: "Members", numeric: true, cell: (cycle) => cycle.active_count },
    { key: "jobs", header: "Jobs", numeric: true, cell: (cycle) => cycle.job_count },
  ];

  return (
    <>
      <PageHeader
        title="Manage cycles"
        subtitle="Recruitment cycles, their membership, and the jobs inside them."
        actions={
          <Button
            variant="primary"
            icon={<Plus className="h-4 w-4" />}
            disabled={!createPermission.allowed}
            title={createPermission.human ?? undefined}
            onClick={() => setCreating((open) => !open)}
          >
            New cycle
          </Button>
        }
      />

      {creating && createPermission.allowed ? <CreateCycleCard onDone={() => setCreating(false)} /> : null}

      <Card>
        <CardHeader>
          <CardTitle>{screen.data ? counted(payload<StaffCyclesPayload>(screen.data).cycles.length, "cycle") : "Cycles"}</CardTitle>
          <div className="flex flex-wrap items-center gap-gap-lg">
            <Field label="Kind">
              {(field) => (
                <Select {...field} value={kind} onChange={(event) => setKind(event.target.value)}>
                  <option value="">Every kind</option>
                  <option value="placement">Placement</option>
                  <option value="internship">Internship</option>
                  <option value="open">Open</option>
                </Select>
              )}
            </Field>
            <label className="flex items-center gap-gap-md text-body-md text-foreground">
              <Checkbox
                checked={includeArchived}
                onChange={(event) => setIncludeArchived(event.target.checked)}
              />
              Show archived
            </label>
          </div>
        </CardHeader>
        {screen.isPending ? (
          <TableSkeleton />
        ) : screen.isError ? (
          <CardBody>
            <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />
          </CardBody>
        ) : (
          <DataTable
            columns={columns}
            rows={payload<StaffCyclesPayload>(screen.data).cycles}
            rowKey={(cycle) => cycle.id}
            empty={
              <CardBody>
                <EmptyState
                  icon={<CalendarRange className="h-8 w-8" />}
                  message="No cycles yet. Create one to start taking memberships."
                />
              </CardBody>
            }
          />
        )}
      </Card>
    </>
  );
}

function CreateCycleCard({ onDone }: { onDone: () => void }) {
  const create = useCommand("create_cycle");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<"placement" | "internship" | "open">("placement");
  const [description, setDescription] = useState("");
  const [opens, setOpens] = useState("");
  const [closes, setCloses] = useState("");
  // CYC-1: informational season bounds. Nothing gates on them — the
  // registration window and the active flag do that — but a cycle created
  // without them needed a second trip to the edit screen to acquire them.
  const [startsOn, setStartsOn] = useState("");
  const [endsOn, setEndsOn] = useState("");

  // datetime-local has no zone; the server stores UTC, so send an instant.
  const toInstant = (value: string) => (value ? new Date(value).toISOString() : null);

  return (
    <Card>
      <CardHeader>
        <CardTitle>New cycle</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {create.isError ? <ErrorState error={create.error} title="Could not create" /> : null}
        <div className="grid gap-gap-lg sm:grid-cols-2">
          <Field label="Name" required>
            {(field) => (
              <Input
                {...field}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Placement 2027"
              />
            )}
          </Field>
          <Field
            label="Kind"
            required
            hint="Placement and internship fix a job's outcome; open does not."
          >
            {(field) => (
              <Select
                {...field}
                value={kind}
                onChange={(event) =>
                  setKind(event.target.value as "placement" | "internship" | "open")
                }
              >
                <option value="placement">Placement</option>
                <option value="internship">Internship</option>
                <option value="open">Open</option>
              </Select>
            )}
          </Field>
          <Field label="Registration opens">
            {(field) => (
              <Input
                {...field}
                type="datetime-local"
                value={opens}
                onChange={(event) => setOpens(event.target.value)}
              />
            )}
          </Field>
          <Field label="Registration closes">
            {(field) => (
              <Input
                {...field}
                type="datetime-local"
                value={closes}
                onChange={(event) => setCloses(event.target.value)}
              />
            )}
          </Field>
          <Field label="Season starts" hint="Informational only; nothing gates on it.">
            {(field) => (
              <Input
                {...field}
                type="date"
                value={startsOn}
                onChange={(event) => setStartsOn(event.target.value)}
              />
            )}
          </Field>
          <Field label="Season ends" hint="Informational only; used to group analytics by year.">
            {(field) => (
              <Input
                {...field}
                type="date"
                value={endsOn}
                onChange={(event) => setEndsOn(event.target.value)}
              />
            )}
          </Field>
        </div>
        <Field label="Description">
          {(field) => (
            <Textarea
              {...field}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
          )}
        </Field>
        <div className="flex items-center gap-gap-md">
          <Button
            variant="primary"
            disabled={!name.trim()}
            loading={create.isPending}
            onClick={() =>
              create.mutate(
                {
                  input: {
                    name: name.trim(),
                    kind,
                    is_active: true,
                    description: description.trim() || null,
                    registration_opens_at: toInstant(opens),
                    registration_closes_at: toInstant(closes),
                    starts_on: startsOn || null,
                    ends_on: endsOn || null,
                  },
                },
                { onSuccess: onDone },
              )
            }
          >
            Create cycle
          </Button>
          <Button variant="ghost" onClick={onDone}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
