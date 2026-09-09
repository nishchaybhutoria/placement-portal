import { useState } from "react";

import type { CommandInput, CommandName, CommandSummary } from "@/api/client";
import { payload, type AdminFindingsPayload, type FindingRow } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import {
  ChangedFieldsPlan,
  ReinstatementPlan,
  TerminationPlan,
} from "@/components/CommandSummaryDetails";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyId } from "@/components/ui/copyId";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/input";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { StatusChip } from "@/components/ui/statusChip";
import { formatDate } from "@/lib/date";
import { humanise } from "@/lib/text";

type ConsistencyRunSummary = CommandSummary<"run_consistency_checker">;

/**
 * Consistency findings (Behavior §16 rule 4, LLD §12).
 *
 * The suggested-fix button is the point of the screen, and it sends *exactly*
 * what the finding carries: the server built the command name and its input
 * from one catalog entry, so the button cannot send something the finding did
 * not suggest. Where the repair needs a decision the subject cannot supply, the
 * row names the command and offers no button rather than one that would be
 * refused the moment it was pressed.
 */
export function Findings() {
  const [status, setStatus] = useState("open");
  const [invariant, setInvariant] = useState("");

  const screen = useScreen("admin/findings", {
    query: { status: status || undefined, invariant: invariant || undefined },
  });

  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<AdminFindingsPayload>(screen.data);
  return (
    <>
      <PageHeader
        title="Findings"
        subtitle="Drift the nightly consistency pass found, each with the command that compensates for it."
        actions={<RunChecker allowed={data.actions.run_checker.allowed} />}
      />

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <span className="text-body-sm text-muted-foreground">
            {data.counts.open ?? 0} open · {data.counts.resolved ?? 0} resolved ·{" "}
            {data.counts.dismissed ?? 0} dismissed
          </span>
        </CardHeader>
        <CardBody className="grid gap-gap-lg sm:grid-cols-2">
          <Field label="Status">
            {(field) => (
              <Select {...field} value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="">Every status</option>
                {data.statuses.map((item) => (
                  <option key={item} value={item}>
                    {humanise(item)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Invariant">
            {(field) => (
              <Select
                {...field}
                value={invariant}
                onChange={(event) => setInvariant(event.target.value)}
              >
                <option value="">Every invariant</option>
                {data.invariants.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.description}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </CardBody>
      </Card>

      {data.findings.length === 0 ? (
        <EmptyState message="Nothing has drifted. The last pass asserted every invariant and found no violation." />
      ) : (
        <div className="flex flex-col gap-gap-lg">
          {data.findings.map((finding) => (
            <FindingCard key={finding.id} finding={finding} />
          ))}
        </div>
      )}
    </>
  );
}

/**
 * Run the nightly pass now (the design review §4.36).
 *
 * The dry run is a complete check that writes nothing, so the preview answers
 * the question an administrator actually has after compensating a finding —
 * did it clear? — before anything is recorded. Confirm then opens, reopens and
 * closes findings exactly as the 03:00 run would, under the operator's name.
 */
function RunChecker({ allowed }: { allowed: boolean }) {
  if (!allowed) return null;
  return (
    <PreviewConfirm
      command="run_consistency_checker"
      input={{}}
      title="Run the consistency checker now?"
      description="Every invariant is asserted against live data. The preview below is that run; confirming records what it found."
      confirmLabel="Run the checker"
      renderSummary={(summary) => <CheckerSummary summary={summary} />}
      trigger={<Button variant="secondary">Run now</Button>}
    />
  );
}

function CheckerSummary({ summary }: { summary: ConsistencyRunSummary }) {
  // "Seven findings" says nothing about which promise the system stopped
  // keeping, so the per-invariant list is shown rather than reduced. The
  // command's own summary types this row as an open object, which is why it is
  // read back through its two known keys rather than cast wholesale.
  const violating = summary.by_invariant
    .map((row) => ({
      invariant: String(row.invariant),
      violations: Number(row.violations ?? 0),
    }))
    .filter((row) => row.violations > 0);
  return (
    <div className="flex flex-col gap-gap-md text-body-md">
      <p className="text-foreground">
        {summary.checked_invariants} invariants checked · {summary.violations} violation
        {summary.violations === 1 ? "" : "s"} · {summary.findings_opened} opened ·{" "}
        {summary.findings_reopened} reopened · {summary.findings_auto_resolved} closed
      </p>
      {violating.length > 0 ? (
        <ul className="flex flex-col gap-gap-tight text-body-sm text-foreground">
          {violating.map((row) => (
            <li key={row.invariant}>
              <span className="font-medium">{row.invariant}</span>
              <span className="text-muted-foreground"> — {row.violations}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-body-sm text-muted-foreground">
          Every invariant holds. Nothing will be recorded.
        </p>
      )}
      <p className="text-body-sm text-muted-foreground">
        Housekeeping: {summary.sessions_purged} expired sessions and{" "}
        {summary.reminder_sends_purged} old reminder records will be purged.
      </p>
    </div>
  );
}

function FindingCard({ finding }: { finding: FindingRow }) {
  return (
    <Card>
      <CardHeader>
        <div>
          <CardTitle>{finding.description}</CardTitle>
          <p className="mt-gap-tight text-body-sm text-muted-foreground">
            {finding.invariant}
            {finding.created_at ? ` · first seen ${formatDate(finding.created_at)}` : ""}
            {finding.resolved_at ? ` · closed ${formatDate(finding.resolved_at)}` : ""}
          </p>
        </div>
        <StatusChip domain="finding" value={finding.status} />
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        <p className="text-body-md text-foreground">{finding.detail}</p>

        <div>
          <h3 className="text-label-caps uppercase text-muted-foreground">Subject</h3>
          <dl className="mt-gap-md grid gap-gap-md sm:grid-cols-2">
            {Object.entries(finding.subject).map(([key, value]) => {
              // The server names every id it could resolve. Where it did, the
              // name is the subject and the id is a copy button; where it did
              // not (a status, a count) the value speaks for itself.
              const label = finding.subject_labels?.[key];
              return (
                <div key={key}>
                  <dt className="text-body-sm text-muted-foreground">{humanise(key)}</dt>
                  <dd className="text-body-sm text-foreground">
                    {label ? (
                      <span className="flex flex-wrap items-center gap-gap-tight">
                        {label}
                        <CopyId value={String(value)} />
                      </span>
                    ) : (
                      String(value)
                    )}
                  </dd>
                </div>
              );
            })}
          </dl>
        </div>

        <div className="flex flex-wrap items-center gap-gap-md">
          <SuggestedFix finding={finding} />
          <Verdict finding={finding} command="resolve_finding" label="Resolve" />
          <Verdict finding={finding} command="dismiss_finding" label="Dismiss" />
        </div>
      </CardBody>
    </Card>
  );
}

function SuggestedFix({ finding }: { finding: FindingRow }) {
  const fix = finding.suggested_fix;
  if (!fix) {
    return (
      <span className="text-body-sm text-muted-foreground">
        No compensating command; this one needs a person.
      </span>
    );
  }
  if (!fix.input) {
    return (
      <span className="text-body-sm text-muted-foreground">
        Repair with <span className="font-medium">{fix.command}</span> — it needs a value only you
        can choose, so it is not prefilled here.
      </span>
    );
  }
  const renderSummary = suggestedFixRenderer(fix.command);
  return (
    <PreviewConfirm
      command={fix.command as CommandName}
      input={fix.input as CommandInput<CommandName>}
      title={`Run ${fix.command}?`}
      description="The preview below is the server's, computed by the same code the confirm will execute."
      confirmLabel={`Run ${fix.command}`}
      destructive
      {...(renderSummary ? { renderSummary } : {})}
      trigger={<Button>Apply suggested fix</Button>}
    />
  );
}

function suggestedFixRenderer(command: string) {
  if (command === "reinstate_application") {
    return (summary: Record<string, unknown>) => <ReinstatementPlan summary={summary} />;
  }
  if (command === "terminate_offer") {
    return (summary: Record<string, unknown>) => <TerminationPlan summary={summary} />;
  }
  if (command === "admin_update_profile") {
    return (summary: Record<string, unknown>) => <ChangedFieldsPlan summary={summary} />;
  }
  return null;
}

function Verdict({
  finding,
  command,
  label,
}: {
  finding: FindingRow;
  command: "resolve_finding" | "dismiss_finding";
  label: string;
}) {
  const permission =
    command === "resolve_finding" ? finding.actions.resolve : finding.actions.dismiss;
  if (!permission.allowed) {
    return null;
  }
  return (
    <PreviewConfirm
      command={command}
      input={{ finding_id: finding.id, reason: "" }}
      title={`${label} this finding?`}
      description={
        command === "resolve_finding"
          ? "The next nightly pass re-opens it if the drift is still there."
          : "Dismissing keeps it quiet while the drift persists; if the invariant holds again it closes itself."
      }
      confirmLabel={label}
      choices={[
        {
          name: "reason",
          label: "Reason",
          kind: "textarea",
          required: true,
          hint: "Audited, so the next administrator can tell a compensated finding from one somebody chose to live with.",
        },
      ]}
      trigger={<Button variant="secondary">{label}</Button>}
    />
  );
}
