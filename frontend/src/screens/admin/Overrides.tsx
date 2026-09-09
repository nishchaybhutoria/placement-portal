import { useState } from "react";

import type { CommandInput } from "@/api/client";
import { payload, type AdminOverridesPayload, type OverrideRow } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { overrideChoices } from "@/components/GrantOverride";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/input";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { StatusChip } from "@/components/ui/statusChip";
import { DataTable, type Column } from "@/components/ui/table";
import { formatDate } from "@/lib/date";
import { humanise } from "@/lib/text";

/**
 * The override register (Behavior INT-2): listed, filterable, one-click off.
 *
 * Nothing here decides whether a row can be deactivated — the server sends that
 * verdict with the row, and the button renders it. The three states are the
 * server's too: `is_active` alone cannot tell a live grant from one whose
 * expiry has passed, and the resolver ignores both kinds of dead row.
 */
export function Overrides() {
  const [domain, setDomain] = useState("");
  const [scope, setScope] = useState("");
  const [state, setState] = useState("");
  const [cycleId, setCycleId] = useState("");

  const screen = useScreen("admin/overrides", {
    query: {
      rule_domain: domain || undefined,
      scope: scope || undefined,
      state: state || undefined,
      cycle_id: cycleId || undefined,
    },
  });

  if (screen.isPending) return <ScreenSkeleton variant="table" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<AdminOverridesPayload>(screen.data);
  const columns: Column<OverrideRow>[] = [
    {
      key: "domain",
      header: "Rule domain",
      cell: (row) => (
        <span>
          <span className="block font-medium">{humanise(row.rule_domain)}</span>
          <span className="block text-body-sm text-muted-foreground">
            {row.allow ? "Allows past the gate" : "Blocks — beats an equal allow"}
          </span>
        </span>
      ),
    },
    {
      key: "scope",
      header: "Scope",
      cell: (row) => (
        <span>
          <span className="block font-medium">{humanise(row.scope)}</span>
          <span className="block text-body-sm text-muted-foreground">
            {row.subject_label || row.subject_id}
          </span>
        </span>
      ),
    },
    { key: "reason", header: "Reason", cell: (row) => row.reason },
    {
      key: "granted",
      header: "Granted",
      cell: (row) => (
        <span className="text-body-sm text-muted-foreground">
          {row.granted_by.name}
          {row.created_at ? ` · ${formatDate(row.created_at)}` : ""}
        </span>
      ),
    },
    {
      key: "state",
      header: "State",
      cell: (row) => (
        <span className="flex flex-col gap-gap-tight">
          <StatusChip domain="override" value={row.state} />
          {row.expires_at ? (
            <span className="text-body-sm text-muted-foreground">
              {row.state === "expired" ? "Expired " : "Expires "}
              {formatDate(row.expires_at)}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      key: "actions",
      header: "",
      cell: (row) => <Deactivate row={row} />,
    },
  ];

  return (
    <>
      <PageHeader
        title="Overrides"
        subtitle="Standing exceptions consulted before any gate enforces. Expired and deactivated rows are inert. A coordinator sees the cycles they coordinate; enrollment-only grants belong to no cycle and are an administrator's to see."
      />

      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <span className="text-body-sm text-muted-foreground">
            {data.counts.active ?? 0} active · {data.counts.expired ?? 0} expired ·{" "}
            {data.counts.deactivated ?? 0} deactivated
          </span>
        </CardHeader>
        <CardBody className="grid gap-gap-lg sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Rule domain">
            {(field) => (
              <Select
                {...field}
                value={domain}
                onChange={(event) => setDomain(event.target.value)}
              >
                <option value="">Every domain</option>
                {data.rule_domains.map((item) => (
                  <option key={item} value={item}>
                    {humanise(item)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Scope">
            {(field) => (
              <Select {...field} value={scope} onChange={(event) => setScope(event.target.value)}>
                <option value="">Every scope</option>
                {data.scopes.map((item) => (
                  <option key={item} value={item}>
                    {humanise(item)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="State">
            {(field) => (
              <Select {...field} value={state} onChange={(event) => setState(event.target.value)}>
                <option value="">Every state</option>
                {data.states.map((item) => (
                  <option key={item} value={item}>
                    {humanise(item)}
                  </option>
                ))}
              </Select>
            )}
          </Field>
          <Field label="Cycle" hint="Enrollment-only grants belong to no cycle.">
            {(field) => (
              <Select
                {...field}
                value={cycleId}
                onChange={(event) => setCycleId(event.target.value)}
              >
                <option value="">Every cycle</option>
                {data.cycles.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </Select>
            )}
          </Field>
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Granted overrides</CardTitle>
          <GrantCycleOverride cycles={data.cycles} domains={data.rule_domains} />
        </CardHeader>
        <CardBody>
          <DataTable
            columns={columns}
            rows={data.overrides}
            rowKey={(row) => row.id}
            empty={<EmptyState message="No override matches these filters." />}
          />
        </CardBody>
      </Card>
    </>
  );
}

function Deactivate({ row }: { row: OverrideRow }) {
  const permission = row.actions.deactivate;
  if (!permission.allowed) {
    return (
      <span className="text-body-sm text-muted-foreground">
        {permission.human ?? "Already deactivated"}
      </span>
    );
  }
  return (
    <PreviewConfirm
      command="deactivate_override"
      input={{ override_id: row.id }}
      title="Deactivate this override?"
      description={`${humanise(row.rule_domain)} · ${row.subject_label || row.subject_id}`}
      confirmLabel="Deactivate"
      destructive
      choices={[
        {
          name: "reason",
          label: "Reason (optional)",
          kind: "text",
          hint: "INT-2 asks for one-click deactivation, so this is not required — it is audited when given.",
        },
      ]}
      trigger={<Button variant="secondary">Deactivate</Button>}
    />
  );
}

function GrantCycleOverride({
  cycles,
  domains,
}: {
  cycles: AdminOverridesPayload["cycles"];
  domains: string[];
}) {
  const [cycleId, setCycleId] = useState(cycles[0]?.id ?? "");
  const initialDomain = (domains[0] ??
    "") as CommandInput<"create_override">["rule_domain"];
  return (
    <div className="flex flex-wrap items-end gap-gap-md">
      <div className="w-56">
        <Field label="Cycle to grant in">
          {(field) => (
            <Select {...field} value={cycleId} onChange={(event) => setCycleId(event.target.value)}>
              {cycles.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          )}
        </Field>
      </div>
      <PreviewConfirm
        command="create_override"
        input={{
          cycle_id: cycleId,
          rule_domain: initialDomain,
          allow: true,
          reason: "",
        }}
        title="Grant a cycle-scoped override"
        description="This lifts the gate for every member of the cycle. To lift it for one student, use Grant an override on their record; for one job, the job builder's Eligibility tab."
        confirmLabel="Grant"
        choices={overrideChoices(domains)}
        trigger={<Button disabled={cycleId === "" || domains.length === 0}>Grant override</Button>}
      />
    </div>
  );
}
