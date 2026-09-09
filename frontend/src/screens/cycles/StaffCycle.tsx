import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import {
  payload,
  type AdminUsersPayload,
  type PolicyValue,
  type StaffCyclePayload,
} from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select, Textarea } from "@/components/ui/input";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { cn } from "@/lib/cn";
import { formatDateTime } from "@/lib/date";
import { humanise } from "@/lib/text";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "@/lib/useDebouncedValue";

/** One cycle: its policy, its coordinators, and its membership (LLD §11.3). */
export function StaffCycle() {
  const { id = "" } = useParams();
  const screen = useScreen("staff/cycle/{id}", { params: { id } });

  if (screen.isPending) return <ScreenSkeleton variant="detail" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<StaffCyclePayload>(screen.data);
  const archived = data.cycle.archived_at !== null;
  const adminManaged = data.actions.manage.allowed;

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link to="/staff/cycles" className="inline-flex items-center gap-gap-tight hover:underline">
            <ArrowLeft className="h-3 w-3" /> All cycles
          </Link>
        }
        title={data.cycle.name}
        subtitle={data.cycle.description ?? undefined}
        actions={
          <>
            <Button asChild variant="secondary">
              <Link to={`/staff/cycles/${id}/jobs`}>Jobs</Link>
            </Button>
            <Button asChild variant="secondary">
              <Link to={`/staff/cycles/${id}/external`}>External offers</Link>
            </Button>
            <Button asChild variant="secondary">
              <Link to={`/staff/cycles/${id}/analytics`}>Analytics</Link>
            </Button>
            <Button asChild variant="primary">
              <Link to={`/staff/cycles/${id}/approvals`}>
                Approvals{data.pending_approvals ? ` (${data.pending_approvals})` : ""}
              </Link>
            </Button>
            {!archived && adminManaged ? (
              <>
                <PreviewConfirm
                  command="set_cycle_active"
                  input={{ cycle_id: id, is_active: !data.cycle.is_active }}
                  title={`${data.cycle.is_active ? "Pause" : "Open"} ${data.cycle.name}?`}
                  confirmLabel={data.cycle.is_active ? "Pause cycle" : "Open cycle"}
                  destructive={data.cycle.is_active}
                  trigger={
                    <Button variant={data.cycle.is_active ? "destructive-ghost" : "secondary"}>
                      {data.cycle.is_active ? "Pause" : "Open"}
                    </Button>
                  }
                />
                <PreviewConfirm
                  command="archive_cycle"
                  input={{ cycle_id: id }}
                  title={`Archive ${data.cycle.name}?`}
                  description="Every non-terminal application is listed in the preview before the cycle becomes permanently read-only."
                  confirmLabel="Archive cycle"
                  destructive
                  renderSummary={(summary) => <ArchiveSummary summary={summary as never} />}
                  trigger={<Button variant="destructive-ghost">Archive</Button>}
                />
              </>
            ) : null}
          </>
        }
      />

      {archived ? (
        <div className="rounded border border-warning-border bg-warning-subtle p-container-padding">
          <p className="text-body-md font-semibold text-warning">This cycle is archived</p>
          <p className="mt-gap-tight text-body-md text-foreground">
            Archived cycles are read-only. Every command scoped to this cycle is rejected.
          </p>
        </div>
      ) : null}

      <div className="grid gap-section-margin lg:grid-cols-[2fr_1fr]">
        <PolicyEditor cycleId={id} policy={data.policy} disabled={archived || !adminManaged} />
        <div className="flex flex-col gap-section-margin">
          <CycleDetails
            cycleId={id}
            data={data}
            disabled={archived || !adminManaged}
          />
          <Coordinators cycleId={id} data={data} disabled={archived || !adminManaged} />
          <CycleFacts data={data} />
        </div>
      </div>

      <MembershipBreakdown
        cycleId={id}
        memberships={data.memberships}
        applications={data.applications}
      />
    </>
  );
}

/**
 * The policy editor. Every row shows the value *and its source*, because a
 * cycle policy is an override over a code default — a plain input would say
 * nothing about which of the two is currently in force.
 */
const BOOLEAN_POLICIES = [
  {
    key: "membership_requires_approval" as const,
    label: "Membership needs approval",
    hint: "Off means joining is immediate, with no queue for staff to work through.",
  },
  {
    key: "penalty_blocks_applications" as const,
    label: "An active penalty blocks applications",
  },
  {
    key: "allow_withdrawal_after_deadline" as const,
    label: "Allow withdrawal after the deadline",
  },
  { key: "allow_edit_after_deadline" as const, label: "Allow edits after the deadline" },
  { key: "strike_on_absence" as const, label: "Absence earns a strike" },
];

function PolicyEditor({
  cycleId,
  policy,
  disabled,
}: {
  cycleId: string;
  policy: StaffCyclePayload["policy"];
  disabled: boolean;
}) {
  const save = useCommand("update_cycle_policy");
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const [joinRuleText, setJoinRuleText] = useState(
    policy.join_rule.value ? JSON.stringify(policy.join_rule.value, null, 2) : "",
  );
  const [joinRuleError, setJoinRuleError] = useState<string | null>(null);
  const dirty = Object.keys(draft).length > 0;

  function changeJoinRule(value: string) {
    setJoinRuleText(value);
    try {
      setDraft((current) => ({
        ...current,
        join_rule: value.trim() ? JSON.parse(value) as Record<string, unknown> : null,
      }));
      setJoinRuleError(null);
    } catch {
      setJoinRuleError("The join rule must be valid JSON before it can be saved.");
    }
  }

  function discard() {
    setDraft({});
    setJoinRuleText(policy.join_rule.value ? JSON.stringify(policy.join_rule.value, null, 2) : "");
    setJoinRuleError(null);
  }

  const read = <T,>(key: keyof StaffCyclePayload["policy"]): T =>
    (key in draft ? draft[key] : (policy[key] as PolicyValue<T>).value) as T;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Policy</CardTitle>
        {dirty ? (
          <div className="flex items-center gap-gap-md">
            <Button variant="ghost" size="sm" onClick={discard}>
              Discard
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={save.isPending}
              disabled={joinRuleError !== null}
              onClick={() =>
                save.mutate(
                  { input: { cycle_id: cycleId, ...draft } },
                  { onSuccess: () => setDraft({}) },
                )
              }
            >
              Save changes
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {save.isError ? <ErrorState error={save.error} title="Could not save policy" /> : null}

        {BOOLEAN_POLICIES.map((row) => (
          <div key={row.key} className="flex flex-col gap-gap-tight">
            <label className="flex items-center gap-gap-md text-body-md text-foreground">
              <Checkbox
                disabled={disabled}
                checked={read<boolean>(row.key)}
                onChange={(event) =>
                  setDraft((prev) => ({ ...prev, [row.key]: event.target.checked }))
                }
              />
              {row.label}
            </label>
            <Source value={policy[row.key]} hint={row.hint} />
          </div>
        ))}

        <Field
          label="Accepted-offer cap"
          hint="Blank means no cap. The cap counts offers a student has accepted in this cycle."
        >
          {(field) => (
            <Input
              {...field}
              type="number"
              min={0}
              disabled={disabled}
              value={read<number | null>("max_accepted_offers") ?? ""}
              onChange={(event) =>
                setDraft((prev) => ({
                  ...prev,
                  max_accepted_offers:
                    event.target.value === "" ? null : Number(event.target.value),
                }))
              }
            />
          )}
        </Field>
        <Source value={policy.max_accepted_offers} />

        <Field
          label="When an offer expires"
          hint="What happens to an offer nobody responded to before its deadline."
        >
          {(field) => (
            <Select
              {...field}
              disabled={disabled}
              value={read<string>("offer_expiry_behavior")}
              onChange={(event) =>
                setDraft((prev) => ({ ...prev, offer_expiry_behavior: event.target.value }))
              }
            >
              <option value="auto_decline">Decline it automatically</option>
              <option value="auto_accept">Accept it automatically</option>
            </Select>
          )}
        </Field>
        <Source value={policy.offer_expiry_behavior} />

        <div className="grid gap-gap-lg sm:grid-cols-2">
          <Field label="Deadline reminder (hours before)">
            {(field) => (
              <Input
                {...field}
                type="number"
                min={0}
                disabled={disabled}
                value={read<number>("deadline_reminder_hours")}
                onChange={(event) => setDraft((current) => ({ ...current, deadline_reminder_hours: Number(event.target.value) }))}
              />
            )}
          </Field>
          <Field label="Round reminder (hours before)">
            {(field) => (
              <Input
                {...field}
                type="number"
                min={0}
                disabled={disabled}
                value={read<number>("round_reminder_hours")}
                onChange={(event) => setDraft((current) => ({ ...current, round_reminder_hours: Number(event.target.value) }))}
              />
            )}
          </Field>
        </div>
        <Source value={policy.deadline_reminder_hours} />
        <Source value={policy.round_reminder_hours} />

        <Field
          label="Join rule (JSON)"
          hint="Blank uses no join rule. This is evaluated before a membership request enters the queue."
          error={joinRuleError ?? undefined}
        >
          {(field) => (
            <Textarea
              {...field}
              className="min-h-[160px]"
              disabled={disabled}
              value={joinRuleText}
              onChange={(event) => changeJoinRule(event.target.value)}
            />
          )}
        </Field>
        <Source value={policy.join_rule} />
      </CardBody>
    </Card>
  );
}

function ArchiveSummary({
  summary,
}: {
  summary: { auto_withdrawn: Record<string, unknown>[]; untouched: Record<string, unknown>[] };
}) {
  const section = (title: string, rows: Record<string, unknown>[]) => (
    <section>
      <p className="text-label-caps uppercase text-muted-foreground">{title} ({rows.length})</p>
      {rows.length === 0 ? (
        <p className="mt-gap-tight text-body-sm text-muted-foreground">None.</p>
      ) : (
        <ul className="mt-gap-tight flex flex-col gap-gap-tight text-body-sm text-foreground">
          {rows.map((row, index) => (
            <li key={String(row.application_id ?? index)}>
              {String(row.full_name ?? "Application")}
              {row.job ? ` · ${String(row.job)}` : ""}
              {row.from_status || row.status
                ? ` · ${humanise(String(row.from_status ?? row.status)).toLowerCase()}`
                : ""}
              {row.suggested_command
                ? ` · use ${humanise(String(row.suggested_command)).toLowerCase()}`
                : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
  return (
    <div className="flex flex-col gap-gap-lg">
      {section("Will auto-withdraw", summary.auto_withdrawn ?? [])}
      {section("Will remain untouched", summary.untouched ?? [])}
    </div>
  );
}

/** Where a policy value came from — the override or the default beneath it. */
function Source({ value, hint }: { value: PolicyValue<unknown>; hint?: string }) {
  return (
    <p className="text-body-sm text-muted-foreground">
      {hint ? `${hint} ` : ""}
      {value.source === "cycle_policy"
        ? "Set on this cycle."
        : `Inherited from ${humanise(value.source).toLowerCase()}.`}
    </p>
  );
}

function Coordinators({
  cycleId,
  data,
  disabled,
}: {
  cycleId: string;
  data: StaffCyclePayload;
  disabled: boolean;
}) {
  const assign = useCommand("assign_coordinator");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Coordinators</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {data.coordinators.length === 0 ? (
          <EmptyState message="Nobody coordinates this cycle yet." />
        ) : (
          <ul className="flex flex-col gap-gap-md">
            {data.coordinators.map((person) => (
              <li
                key={person.user_id}
                className="flex items-center justify-between gap-gap-md"
              >
                <div className="min-w-0">
                  <p className="truncate text-body-md text-foreground">{person.full_name}</p>
                  <p className="truncate text-body-sm text-muted-foreground">{person.email}</p>
                </div>
                <PreviewConfirm
                  command="remove_coordinator"
                  input={{ cycle_id: cycleId, user_id: person.user_id }}
                  title="Remove this coordinator?"
                  description={`${person.full_name} will lose staff access to this cycle.`}
                  confirmLabel="Remove"
                  destructive
                  trigger={
                    <Button variant="destructive-ghost" size="sm" disabled={disabled}>
                      Remove
                    </Button>
                  }
                />
              </li>
            ))}
          </ul>
        )}

        <CoordinatorPicker
          disabled={disabled}
          assigned={data.coordinators.map((person) => person.user_id)}
          onPick={(pickedUserId) =>
            assign.mutate({ input: { cycle_id: cycleId, user_id: pickedUserId } })
          }
          pending={assign.isPending}
        />
        {assign.isError ? <ErrorState error={assign.error} title="Could not assign" /> : null}
      </CardBody>
    </Card>
  );
}

/**
 * The cycle's own fields, including the registration window (Behavior CYC-1).
 *
 * `update_cycle` has existed since M4 with no screen, so the window was set
 * once at creation and could only be moved by an API call — which is a problem
 * the moment a deadline needs extending, because `_window_reasons` refuses
 * every join outside it and the office has no other lever.
 *
 * The kind is deliberately absent: CYC-1 fixes it at creation, and the command
 * rejects a change rather than pretending otherwise.
 */
function CycleDetails({
  cycleId,
  data,
  disabled,
}: {
  cycleId: string;
  data: StaffCyclePayload;
  disabled: boolean;
}) {
  const save = useCommand("update_cycle");
  const cycle = data.cycle;
  const [draft, setDraft] = useState<Partial<Record<CycleField, string>>>({});
  const dirty = Object.keys(draft).length > 0;

  // Every value is held as the string its input renders, and converted once at
  // submit. A display-only mirror kept alongside the wire value in the same bag
  // is what makes an `extra="forbid"` command 422 on save.
  const read = (key: CycleField) => draft[key] ?? stored(cycle, key);
  const set = (key: CycleField, value: string) =>
    setDraft((prev) => ({ ...prev, [key]: value }));

  function submit() {
    const input: Record<string, unknown> = { cycle_id: cycleId };
    for (const key of Object.keys(draft) as CycleField[]) {
      const value = draft[key] ?? "";
      input[key] =
        key === "registration_opens_at" || key === "registration_closes_at"
          ? value
            ? new Date(value).toISOString()
            : null
          : value.trim() || null;
    }
    save.mutate({ input: input as never }, { onSuccess: () => setDraft({}) });
  }

  if (disabled) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Cycle details</CardTitle>
        {dirty ? (
          <div className="flex items-center gap-gap-md">
            <Button variant="ghost" size="sm" onClick={() => setDraft({})}>
              Discard
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={save.isPending}
              onClick={submit}
            >
              Save
            </Button>
          </div>
        ) : null}
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {save.isError ? <ErrorState error={save.error} title="Could not save" /> : null}
        <Field label="Name" required>
          {(field) => (
            <Input
              {...field}
              value={read("name")}
              onChange={(event) => set("name", event.target.value)}
            />
          )}
        </Field>
        <Field label="Description">
          {(field) => (
            <Input
              {...field}
              value={read("description")}
              onChange={(event) => set("description", event.target.value)}
            />
          )}
        </Field>
        <div className="grid gap-gap-lg sm:grid-cols-2">
          <Field
            label="Registration opens"
            hint="Leave blank to open as soon as the cycle is active."
          >
            {(field) => (
              <Input
                {...field}
                type="datetime-local"
                value={read("registration_opens_at")}
                onChange={(event) => set("registration_opens_at", event.target.value)}
              />
            )}
          </Field>
          <Field
            label="Registration closes"
            hint="Students may join up to this instant, not including it."
          >
            {(field) => (
              <Input
                {...field}
                type="datetime-local"
                value={read("registration_closes_at")}
                onChange={(event) =>
                  set("registration_closes_at", event.target.value)
                }
              />
            )}
          </Field>
          <Field label="Starts on" hint="Informational: display and year grouping only.">
            {(field) => (
              <Input
                {...field}
                type="date"
                value={read("starts_on")}
                onChange={(event) => set("starts_on", event.target.value)}
              />
            )}
          </Field>
          <Field label="Ends on" hint="Informational; no behaviour gates on it.">
            {(field) => (
              <Input
                {...field}
                type="date"
                value={read("ends_on")}
                onChange={(event) => set("ends_on", event.target.value)}
              />
            )}
          </Field>
        </div>
      </CardBody>
    </Card>
  );
}

type CycleField =
  | "name"
  | "description"
  | "starts_on"
  | "ends_on"
  | "registration_opens_at"
  | "registration_closes_at";

/** The stored value as the matching input renders it. */
function stored(cycle: StaffCyclePayload["cycle"], key: CycleField): string {
  const value = cycle[key];
  if (typeof value !== "string") return "";
  // `datetime-local` wants `YYYY-MM-DDTHH:mm`; a date input wants the day.
  if (key === "registration_opens_at" || key === "registration_closes_at") {
    return value.slice(0, 16);
  }
  return value;
}


function CycleFacts({ data }: { data: StaffCyclePayload }) {
  const when = (value: string | null) =>
    value ? formatDateTime(value) : "Not set";
  return (
    <Card>
      <CardHeader>
        <CardTitle>At a glance</CardTitle>
      </CardHeader>
      <CardBody>
        <dl className="flex flex-col gap-gap-lg text-body-md">
          {[
            ["Kind", humanise(data.cycle.kind)],
            ["Registration opens", when(data.cycle.registration_opens_at)],
            ["Registration closes", when(data.cycle.registration_closes_at)],
            [
              "Members",
              String(Object.values(data.memberships).reduce((a, b) => a + b, 0)),
            ],
            ["Awaiting approval", String(data.pending_approvals)],
            [
              "Applications",
              String(Object.values(data.applications).reduce((a, b) => a + b, 0)),
            ],
          ].map(([label, value], index) => (
            <div key={index} className="flex items-baseline justify-between gap-gap-lg">
              <dt className="text-muted-foreground">{label}</dt>
              <dd className="text-right text-foreground">{value}</dd>
            </div>
          ))}
        </dl>
      </CardBody>
    </Card>
  );
}

/**
 * The membership breakdown.
 *
 * `staff/cycle/{id}` carries counts per status, not a roster — the roster with
 * per-person actions is the approvals screen, which is where a decision is
 * actually made. Showing a count and linking there beats inventing a table the
 * server has no rows for.
 */
function MembershipBreakdown({
  cycleId,
  memberships,
  applications,
}: {
  cycleId: string;
  memberships: Record<string, number>;
  applications: Record<string, number>;
}) {
  const membershipRows = Object.entries(memberships);
  const applicationRows = Object.entries(applications);

  return (
    <div className="grid gap-section-margin lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Membership</CardTitle>
          <Button asChild variant="ghost" size="sm">
            <Link to={`/staff/cycles/${cycleId}/approvals`}>Open the queue</Link>
          </Button>
        </CardHeader>
        <CardBody>
          {membershipRows.length === 0 ? (
            <EmptyState message="Nobody has joined this cycle yet." />
          ) : (
            <ul className="flex flex-col gap-gap-lg">
              {membershipRows.map(([status, count]) => (
                <li key={status} className="flex items-center justify-between gap-gap-lg">
                  <StatusChip domain="membership" value={status} />
                  <span className="tabular text-headline-md text-foreground">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Applications</CardTitle>
        </CardHeader>
        <CardBody>
          {applicationRows.length === 0 ? (
            <EmptyState message="No applications have been filed in this cycle." />
          ) : (
            <ul className="flex flex-col gap-gap-lg">
              {applicationRows.map(([status, count]) => (
                <li key={status} className="flex items-center justify-between gap-gap-lg">
                  <StatusChip domain="application" value={status} />
                  <span className="tabular text-headline-md text-foreground">{count}</span>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}


/**
 * Find the person, send the id.
 *
 * `assign_coordinator` takes a `user_id` and nothing else, which left this
 * field asking an administrator to paste a UUID the portal never shows them
 * anywhere — the only way to obtain one was the database. The id is still what
 * goes over the wire; what changed is that a human now picks a name.
 *
 * The search is the `admin/users` screen, which already matches on name, email
 * or roll number. Both it and this command are admin-only, so nothing here
 * widens what the searcher can see — and the server authorises the assignment
 * independently regardless.
 */
function CoordinatorPicker({
  assigned,
  disabled,
  pending,
  onPick,
}: {
  assigned: readonly string[];
  disabled: boolean;
  pending: boolean;
  onPick: (userId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const trimmed = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS);
  const results = useScreen("admin/users", {
    query: { q: trimmed || undefined, include_inactive: false },
    enabled: trimmed.length > 1,
    keepPrevious: true,
  });
  const users = results.data
    ? payload<AdminUsersPayload>(results.data).users.filter(
        (user) => !assigned.includes(user.id),
      )
    : [];

  return (
    <Field
      label="Assign a coordinator"
      hint="Search by name, email or roll number. Coordinating a cycle is what grants staff access to it."
    >
      {(field) => (
        <div className="flex flex-col gap-gap-md">
          <Input
            {...field}
            disabled={disabled}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Priya Nair, priya@example.edu, 21110042"
            autoComplete="off"
          />
          {trimmed.length <= 1 ? null : results.isPending ? (
            <p className="text-body-sm text-muted-foreground">Searching…</p>
          ) : users.length === 0 ? (
            <p className="text-body-sm text-muted-foreground">
              Nobody active matches “{trimmed}”.
            </p>
          ) : (
            <ul className="flex max-h-64 flex-col gap-gap-tight overflow-y-auto rounded border border-border p-gap-tight">
              {users.slice(0, 10).map((user) => (
                <li key={user.id}>
                  <button
                    type="button"
                    disabled={disabled || pending}
                    onClick={() => {
                      onPick(user.id);
                      setQuery("");
                    }}
                    className={cn(
                      "flex w-full flex-col items-start rounded px-gap-md py-gap-tight text-left transition-colors",
                      "hover:bg-muted focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
                      "disabled:cursor-not-allowed disabled:opacity-50",
                    )}
                  >
                    <span className="text-body-md text-foreground">{user.full_name}</span>
                    <span className="text-body-sm text-muted-foreground">
                      {[user.email, user.current_enrollment?.roll_number]
                        .filter(Boolean)
                        .join(" · ")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Field>
  );
}
