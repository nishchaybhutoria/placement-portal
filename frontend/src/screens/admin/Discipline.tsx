import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { payload, type DisciplinePayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { DataTable, type Column } from "@/components/ui/table";
import { formatDateTime } from "@/lib/date";
import { counted } from "@/lib/text";

/** Admin discipline roster and per-enrollment history (Behavior DIS). */
export function Discipline() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("enrollment_id") ?? "";
  const [search, setSearch] = useState("");
  const screen = useScreen("admin/discipline", {
    query: { enrollment_id: selected || undefined },
  });

  if (screen.isPending) return <ScreenSkeleton variant="table" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<DisciplinePayload>(screen.data);
  const needle = search.trim().toLowerCase();
  const roster = data.roster.filter((row) =>
    [row.full_name, row.email, row.roll_number ?? ""].some((value) =>
      value.toLowerCase().includes(needle),
    ),
  );
  const threshold = data.threshold.value;

  const columns: Column<DisciplinePayload["roster"][number]>[] = [
    {
      key: "student",
      header: "Student",
      cell: (row) => (
        <span>
          <span className="block font-medium">{row.full_name}</span>
          <span className="block text-body-sm text-muted-foreground">
            {row.roll_number ? `${row.roll_number} · ` : ""}
            {row.email}
          </span>
        </span>
      ),
    },
    { key: "strikes", header: "Active strikes", numeric: true, cell: (row) => row.active_strikes },
    {
      key: "penalties",
      header: "Active penalties",
      numeric: true,
      cell: (row) => row.active_penalties,
    },
    {
      key: "standing",
      header: "Standing",
      cell: (row) => (
        <span className={row.blocked ? "font-semibold text-danger" : "text-muted-foreground"}>
          {row.blocked ? "Penalty active" : "Clear"}
        </span>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Discipline"
        subtitle={
          threshold === null
            ? `Strike conversion is disabled · ${sourceLabel(data.threshold.source)}`
            : `${counted(threshold, "strike")} ${threshold === 1 ? "converts" : "convert"} to one penalty · ${sourceLabel(data.threshold.source)}`
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Students</CardTitle>
          <span className="text-body-sm text-muted-foreground">{counted(data.roster.length, "enrollment")}</span>
        </CardHeader>
        <CardBody className="flex flex-col gap-gap-lg">
          <div className="max-w-sm">
            <Field label="Search" hint="Name, roll number, or institute email.">
              {(field) => (
                <Input
                  {...field}
                  type="search"
                  value={search}
                  placeholder="Asha, 21110001…"
                  onChange={(event) => setSearch(event.target.value)}
                />
              )}
            </Field>
          </div>
          <DataTable
            columns={columns}
            rows={roster}
            rowKey={(row) => row.enrollment_id}
            isSelected={(row) => row.enrollment_id === selected}
            onRowClick={(row) => setParams({ enrollment_id: row.enrollment_id })}
            empty={<EmptyState message="No enrollment matches that search." />}
          />
        </CardBody>
      </Card>

      {selected === "" ? (
        <EmptyState message="Select a student to review or change their disciplinary record." />
      ) : data.student ? (
        <StudentPanel student={data.student} threshold={threshold} />
      ) : (
        <EmptyState message="That enrollment no longer exists." />
      )}
    </>
  );
}

function StudentPanel({
  student,
  threshold,
}: {
  student: NonNullable<DisciplinePayload["student"]>;
  threshold: number | null;
}) {
  return (
    <div className="flex flex-col gap-gap-lg">
      <Card>
        <CardHeader>
          <div>
            <CardTitle>{student.full_name}</CardTitle>
            <p className="mt-gap-tight text-body-sm text-muted-foreground">
              {student.roll_number ? `${student.roll_number} · ` : ""}
              {student.email}
            </p>
          </div>
          <div className="flex flex-wrap gap-gap-md">
            <Button asChild variant="ghost">
              <Link to={`/staff/student/${student.enrollment_id}`}>Open full record</Link>
            </Button>
            <AwardStrike enrollmentId={student.enrollment_id} name={student.full_name} />
            <AwardPenalty enrollmentId={student.enrollment_id} name={student.full_name} />
          </div>
        </CardHeader>
        <CardBody>
          <dl className="grid gap-gap-lg sm:grid-cols-3">
            <Metric label="Active strikes" value={student.active_strikes} />
            <Metric label="Active penalties" value={student.active_penalties} danger={student.active_penalties > 0} />
            <Metric
              label="To next penalty"
              value={
                threshold === null
                  ? "Conversion off"
                  : `${student.strikes_to_next_penalty ?? threshold} strike${student.strikes_to_next_penalty === 1 ? "" : "s"}`
              }
            />
          </dl>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Strike history</CardTitle>
          <span className="text-body-sm text-muted-foreground">{counted(student.strikes.length, "strike")}</span>
        </CardHeader>
        <CardBody>
          {student.strikes.length === 0 ? (
            <EmptyState message="No strikes have been awarded." />
          ) : (
            <ul className="flex flex-col gap-gap-md">
              {student.strikes.map((strike) => (
                <li key={strike.id} className="flex flex-wrap items-start gap-gap-lg rounded border border-border p-gap-lg">
                  <div className="min-w-0 flex-1">
                    <p className="text-body-md font-medium text-foreground">{strike.reason}</p>
                    <p className="mt-gap-tight text-body-sm text-muted-foreground">
                      {strike.source === "auto_absence" ? "Automatic absence" : "Manual"}
                      {strike.created_at ? ` · ${formatDateTime(strike.created_at)}` : ""}
                      {strike.awarded_by?.name ? ` · by ${strike.awarded_by.name}` : ""}
                    </p>
                    <p className="mt-gap-tight text-body-sm text-muted-foreground">
                      {strike.is_active
                        ? strike.consumed_by_penalty_id
                          ? "Active · converted into a penalty"
                          : "Active · unconsumed"
                        : `Revoked${strike.updated_at ? ` · ${formatDateTime(strike.updated_at)}` : ""}`}
                    </p>
                  </div>
                  <RevokeStrike strike={strike} />
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Penalty history</CardTitle>
          <span className="text-body-sm text-muted-foreground">{counted(student.penalties.length, "penalty", "penalties")}</span>
        </CardHeader>
        <CardBody>
          {student.penalties.length === 0 ? (
            <EmptyState message="No penalties have been awarded." />
          ) : (
            <ul className="flex flex-col gap-gap-md">
              {student.penalties.map((penalty) => (
                <li key={penalty.id} className="flex flex-wrap items-start gap-gap-lg rounded border border-border p-gap-lg">
                  <div className="min-w-0 flex-1">
                    <p className="text-body-md font-medium text-foreground">{penalty.reasons}</p>
                    <p className="mt-gap-tight text-body-sm text-muted-foreground">
                      {penalty.from_strikes ? "Converted from strikes" : "Direct penalty"}
                      {penalty.created_at ? ` · ${formatDateTime(penalty.created_at)}` : ""}
                      {penalty.created_by?.name ? ` · by ${penalty.created_by.name}` : ""}
                    </p>
                    <p className="mt-gap-tight text-body-sm text-muted-foreground">
                      {penalty.is_active
                        ? "Active · blocks applications where the cycle policy enables the gate"
                        : `Revoked${penalty.revoked_at ? ` · ${formatDateTime(penalty.revoked_at)}` : ""}${penalty.revoked_by?.name ? ` · by ${penalty.revoked_by.name}` : ""}`}
                    </p>
                  </div>
                  <RevokePenalty penalty={penalty} />
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function Metric({ label, value, danger = false }: { label: string; value: string | number; danger?: boolean }) {
  return (
    <div>
      <dt className="text-label-caps uppercase text-muted-foreground">{label}</dt>
      <dd className={`mt-gap-tight text-headline-md tabular ${danger ? "text-danger" : "text-foreground"}`}>
        {value}
      </dd>
    </div>
  );
}

function AwardStrike({ enrollmentId, name }: { enrollmentId: string; name: string }) {
  return (
    <PreviewConfirm
      command="award_strike"
      input={{ enrollment_id: enrollmentId, reason: "" }}
      title={`Award a strike to ${name}?`}
      confirmLabel="Award strike"
      destructive
      choices={[
        {
          name: "reason",
          label: "Reason",
          kind: "textarea",
          required: true,
          hint: "Recorded on the strike and included in the student's notification.",
        },
      ]}
      trigger={<Button variant="secondary">Award strike</Button>}
    />
  );
}

function AwardPenalty({ enrollmentId, name }: { enrollmentId: string; name: string }) {
  return (
    <PreviewConfirm
      command="award_penalty"
      input={{ enrollment_id: enrollmentId, reasons: "" }}
      title={`Award a penalty to ${name}?`}
      confirmLabel="Award penalty"
      destructive
      choices={[
        {
          name: "reasons",
          label: "Reasons",
          kind: "textarea",
          required: true,
          hint: "A direct penalty consumes no strikes.",
        },
      ]}
      trigger={<Button variant="secondary">Award penalty</Button>}
    />
  );
}

function RevokeStrike({
  strike,
}: {
  strike: NonNullable<DisciplinePayload["student"]>["strikes"][number];
}) {
  const permission = strike.actions.revoke;
  return (
    <PreviewConfirm
      command="revoke_strike"
      input={{ strike_id: strike.id, reason: "" }}
      title="Revoke this strike?"
      description="Automatic penalties supported by this strike may be dissolved and the remaining strikes regrouped."
      confirmLabel="Revoke strike"
      destructive
      choices={[{ name: "reason", label: "Reason", kind: "textarea", required: true }]}
      trigger={
        <Button variant="ghost" disabled={!permission.allowed} title={permission.human ?? undefined}>
          Revoke
        </Button>
      }
    />
  );
}

function RevokePenalty({
  penalty,
}: {
  penalty: NonNullable<DisciplinePayload["student"]>["penalties"][number];
}) {
  const permission = penalty.actions.revoke;
  return (
    <PreviewConfirm
      command="revoke_penalty"
      input={{ penalty_id: penalty.id, reason: "" }}
      title="Revoke this penalty?"
      description="Any strikes consumed when the penalty was created remain consumed."
      confirmLabel="Revoke penalty"
      destructive
      choices={[{ name: "reason", label: "Reason", kind: "textarea", required: true }]}
      trigger={
        <Button variant="ghost" disabled={!permission.allowed} title={permission.human ?? undefined}>
          Revoke
        </Button>
      }
    />
  );
}

function sourceLabel(source: string): string {
  return source === "setting" ? "set by administrators" : "using the code default";
}
