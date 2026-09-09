import { useState } from "react";

import { payload, type ExternalOfferScreenRow, type StaffExternalPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { ExternalOfferPlan } from "@/components/CommandSummaryDetails";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select } from "@/components/ui/input";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { humanise } from "@/lib/text";
import { SEARCH_DEBOUNCE_MS, useDebouncedValue } from "@/lib/useDebouncedValue";

export function ExternalOffers() {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [outcome, setOutcome] = useState("");
  const [attached, setAttached] = useState("");
  const search = useDebouncedValue(query.trim(), SEARCH_DEBOUNCE_MS);
  const screen = useScreen("staff/external", {
    query: {
      q: search || undefined,
      status: status || undefined,
      outcome: outcome || undefined,
      attached: attached === "" ? undefined : attached === "true",
    },
    keepPrevious: true,
  });
  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }
  const data = payload<StaffExternalPayload>(screen.data);
  return (
    <>
      <PageHeader
        title="External offers"
        subtitle="PPOs and off-campus offers, including the pool waiting for a cycle."
        actions={<CreateExternal data={data} />}
      />
      <Card>
        <CardHeader><CardTitle>Filters</CardTitle></CardHeader>
        <CardBody className="grid gap-gap-lg sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Search">
            {(field) => <Input {...field} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Student, roll, or company" />}
          </Field>
          <Field label="Status">
            {(field) => (
              <Select {...field} value={status} onChange={(event) => setStatus(event.target.value)}>
                <option value="">Every status</option>
                <option value="offered">Offered</option>
                <option value="accepted">Accepted</option>
                <option value="declined">Declined</option>
              </Select>
            )}
          </Field>
          <Field label="Outcome">
            {(field) => (
              <Select {...field} value={outcome} onChange={(event) => setOutcome(event.target.value)}>
                <option value="">Every outcome</option>
                <option value="placement">Placement</option>
                <option value="internship">Internship</option>
              </Select>
            )}
          </Field>
          <Field label="Attachment">
            {(field) => (
              <Select {...field} value={attached} onChange={(event) => setAttached(event.target.value)}>
                <option value="">Attached and unattached</option>
                <option value="true">Attached</option>
                <option value="false">Unattached</option>
              </Select>
            )}
          </Field>
        </CardBody>
      </Card>
      <Card>
        <CardHeader><CardTitle>All records ({data.offers.length})</CardTitle></CardHeader>
        <CardBody>
          {data.offers.length === 0 ? (
            <EmptyState message="No external offer has been recorded." />
          ) : (
            <ul className="flex flex-col gap-gap-md">
              {data.offers.map((row) => (
                <ExternalRow key={row.id} row={row} companies={data.companies} />
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </>
  );
}

function CreateExternal({ data }: { data: StaffExternalPayload }) {
  return (
    <CreateExternalOffer
      enrollments={data.enrollments}
      companies={data.companies}
      trigger={
        <Button disabled={!data.actions.create.allowed} title={data.actions.create.human ?? undefined}>
          Record external offer
        </Button>
      }
    />
  );
}

const OUTCOME_CHOICES = [
  { value: "placement", label: "Placement" },
  { value: "internship", label: "Internship" },
] as const;
const SOURCE_CHOICES = [
  { value: "ppo", label: "PPO" },
  { value: "off_campus", label: "Off campus" },
  { value: "other", label: "Other" },
] as const;
const STATUS_CHOICES = [
  { value: "offered", label: "Offered" },
  { value: "accepted", label: "Accepted" },
  { value: "declined", label: "Declined" },
] as const;

/** EXT-1's complete standalone record, including outcome-specific compensation. */
export function CreateExternalOffer({
  enrollments,
  companies,
  preset,
  trigger,
}: {
  enrollments: StaffExternalPayload["enrollments"];
  companies: StaffExternalPayload["companies"];
  preset?: {
    enrollment_id: string;
    company_id: string;
    source_application_id: string;
    student: string;
    company: string;
  };
  trigger: React.ReactNode;
}) {
  return (
    <PreviewConfirm
      command="create_external_offer"
      input={{
        enrollment_id: preset?.enrollment_id ?? "",
        company_id: preset?.company_id ?? "",
        outcome: "placement",
        source: preset ? "ppo" : "off_campus",
        ctc_lpa: null,
        stipend_month: null,
        status: "offered",
        offered_on: null,
        responded_on: null,
        source_application_id: preset?.source_application_id ?? null,
        notes: null,
        reason: "",
        notify: true,
      }}
      transformInput={(input) => ({
        ...input,
        ctc_lpa: input.outcome === "placement" && input.ctc_lpa !== "" ? input.ctc_lpa : null,
        stipend_month: input.outcome === "internship" && input.stipend_month !== "" ? input.stipend_month : null,
        notes: input.notes || null,
      })}
      title={preset ? `Record ${preset.student}'s PPO` : "Record an external offer"}
      confirmLabel="Record offer"
      choices={[
        ...(preset
          ? []
          : [
              {
                name: "enrollment_id",
                label: "Student",
                kind: "select" as const,
                required: true,
                options: enrollments.map((row) => ({
                  value: row.id,
                  label: `${row.full_name}${row.roll_number ? ` (${row.roll_number})` : ""}`,
                })),
              },
              {
                name: "company_id",
                label: "Company",
                kind: "select" as const,
                required: true,
                options: companies.map((row) => ({ value: row.id, label: row.name })),
              },
            ]),
        {
          name: "outcome",
          label: "Outcome",
          kind: "select",
          required: true,
          initialValue: "placement",
          options: OUTCOME_CHOICES,
        },
        {
          name: "ctc_lpa",
          label: "CTC (LPA)",
          kind: "number",
          hint: "The external placement's own annual CTC.",
          visibleWhen: { name: "outcome", value: "placement" },
        },
        {
          name: "stipend_month",
          label: "Stipend per month (INR)",
          kind: "number",
          hint: "The external internship's own monthly stipend.",
          visibleWhen: { name: "outcome", value: "internship" },
        },
        {
          name: "source",
          label: "Source",
          kind: "select",
          required: true,
          initialValue: preset ? "ppo" : "off_campus",
          options: SOURCE_CHOICES,
        },
        {
          name: "status",
          label: "Status",
          kind: "select",
          required: true,
          initialValue: "offered",
          options: STATUS_CHOICES,
        },
        { name: "offered_on", label: "Offer date", kind: "date" },
        { name: "responded_on", label: "Response date", kind: "date" },
        { name: "notes", label: "Notes", kind: "textarea" },
        { name: "reason", label: "Reason / evidence", kind: "textarea", required: true },
        {
          name: "notify",
          label: "Student notification",
          kind: "select",
          coerce: "boolean",
          initialValue: "true",
          options: [
            { value: "true", label: "Notify the student" },
            { value: "false", label: "Do not notify" },
          ],
        },
      ]}
      renderSummary={(summary) => (
        <ExternalOfferPlan summary={summary as unknown as Record<string, unknown>} />
      )}
      choiceContent={preset ? (
        <p className="text-body-sm text-muted-foreground">
          {preset.student} · {preset.company} · linked to this internship application
        </p>
      ) : undefined}
      trigger={trigger}
    />
  );
}

function ExternalRow({
  row,
  companies,
}: {
  row: ExternalOfferScreenRow;
  companies: StaffExternalPayload["companies"];
}) {
  const [restore, setRestore] = useState<string[]>([]);
  const candidates = row.restoration_candidates ?? [];
  const selected = candidates
    .filter((candidate) => restore.includes(candidate.application_id))
    .map((candidate) => ({ application_id: candidate.application_id }));
  return (
    <li className="rounded border border-border p-gap-lg">
      <div className="flex flex-wrap items-start gap-gap-md">
        <div className="min-w-0 flex-1">
          <p className="text-body-md font-medium text-foreground">
            {row.student} · {row.company.name}
          </p>
          <p className="text-body-sm text-muted-foreground">
            {humanise(row.source)} · {humanise(row.outcome)}
            {row.attached_cycle ? ` · ${row.attached_cycle.name}` : " · unattached"}
          </p>
          <p className="text-body-sm text-muted-foreground">
            {row.ctc_lpa ? `${row.ctc_lpa} LPA` : row.stipend_month ? `${row.stipend_month}/month` : "Compensation not recorded"}
          </p>
        </div>
        <StatusChip domain="external" value={row.status} />
      </div>

      {candidates.length > 0 ? (
        <fieldset className="mt-gap-md rounded border border-border p-gap-md">
          <legend className="px-gap-tight text-label-caps uppercase text-muted-foreground">
            Restore if acceptance is reversed
          </legend>
          <div className="flex flex-col gap-gap-md">
            {candidates.map((candidate) => (
              <label key={candidate.application_id} className="flex items-start gap-gap-md text-body-sm">
                <Checkbox
                  checked={restore.includes(candidate.application_id)}
                  disabled={!candidate.can_restore}
                  onChange={(event) =>
                    setRestore((current) =>
                      event.target.checked
                        ? [...current, candidate.application_id]
                        : current.filter((item) => item !== candidate.application_id),
                    )
                  }
                />
                <span className="flex flex-wrap items-center gap-gap-md">
                  <span>{candidate.job}</span>
                  <span aria-hidden>→</span>
                  <StatusChip domain="application" value={candidate.restore_status} />
                  {candidate.requires_fresh_offer ? <span>fresh offer</span> : null}
                  {!candidate.can_restore && candidate.blocked_reason ? (
                    <span className="basis-full text-danger">{candidate.blocked_reason}</span>
                  ) : null}
                </span>
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      <div className="mt-gap-md flex flex-wrap gap-gap-md">
        <PreviewConfirm
          command="update_external_offer"
          input={{
            external_offer_id: row.id,
            expected_status: row.status as "offered" | "accepted" | "declined",
            company_id: row.company.id,
            outcome: row.outcome as "placement" | "internship",
            source: row.source as "ppo" | "off_campus" | "other",
            ctc_lpa: row.ctc_lpa,
            stipend_month: row.stipend_month,
            status: row.status as "offered" | "accepted" | "declined",
            offered_on: row.offered_on,
            responded_on: row.responded_on,
            source_application_id: row.source_application_id,
            notes: row.notes,
            reason: "",
            restore: selected,
            clear_ctc_lpa: false,
            clear_stipend_month: false,
            clear_offered_on: false,
            clear_responded_on: false,
            clear_source_application: false,
            clear_notes: false,
            notify: true,
          }}
          transformInput={(input) => {
            const ctc = input.outcome === "placement" && input.ctc_lpa !== "" ? input.ctc_lpa : null;
            const stipend = input.outcome === "internship" && input.stipend_month !== "" ? input.stipend_month : null;
            const offeredOn = input.offered_on || null;
            const respondedOn = input.responded_on || null;
            const notes = input.notes || null;
            return {
              ...input,
              ctc_lpa: ctc,
              stipend_month: stipend,
              offered_on: offeredOn,
              responded_on: respondedOn,
              notes,
              clear_ctc_lpa: row.ctc_lpa !== null && ctc === null,
              clear_stipend_month: row.stipend_month !== null && stipend === null,
              clear_offered_on: row.offered_on !== null && offeredOn === null,
              clear_responded_on: row.responded_on !== null && respondedOn === null,
              clear_notes: row.notes !== null && notes === null,
              source_application_id: input.clear_source_application ? null : input.source_application_id,
            };
          }}
          title={`Update ${row.student}'s external offer?`}
          confirmLabel="Update"
          renderSummary={(summary) => (
            <ExternalOfferPlan summary={summary as unknown as Record<string, unknown>} />
          )}
          choices={[
            {
              name: "company_id",
              label: "Company",
              kind: "select",
              required: true,
              initialValue: row.company.id,
              options: companies.map((company) => ({ value: company.id, label: company.name })),
            },
            {
              name: "outcome",
              label: "Outcome",
              kind: "select",
              required: true,
              initialValue: row.outcome,
              options: OUTCOME_CHOICES,
            },
            {
              name: "ctc_lpa",
              label: "CTC (LPA)",
              kind: "number",
              initialValue: row.ctc_lpa ?? "",
              visibleWhen: { name: "outcome", value: "placement" },
            },
            {
              name: "stipend_month",
              label: "Stipend per month (INR)",
              kind: "number",
              initialValue: row.stipend_month ?? "",
              visibleWhen: { name: "outcome", value: "internship" },
            },
            {
              name: "source",
              label: "Source",
              kind: "select",
              required: true,
              initialValue: row.source,
              options: SOURCE_CHOICES,
            },
            {
              name: "status",
              label: "Status",
              kind: "select",
              required: true,
              initialValue: row.status,
              options: STATUS_CHOICES,
            },
            { name: "offered_on", label: "Offer date", kind: "date", initialValue: row.offered_on ?? "" },
            { name: "responded_on", label: "Response date", kind: "date", initialValue: row.responded_on ?? "" },
            { name: "notes", label: "Notes", kind: "textarea", initialValue: row.notes ?? "" },
            ...(row.source_application_id
              ? [{
                  name: "clear_source_application",
                  label: "Source application link",
                  kind: "select" as const,
                  coerce: "boolean" as const,
                  initialValue: "false",
                  options: [
                    { value: "false", label: "Keep linked application" },
                    { value: "true", label: "Clear linked application" },
                  ],
                }]
              : []),
            { name: "reason", label: "Reason", kind: "textarea", required: true },
            {
              name: "notify",
              label: "Student notification",
              kind: "select",
              coerce: "boolean",
              initialValue: "true",
              options: [
                { value: "true", label: "Notify the student" },
                { value: "false", label: "Do not notify" },
              ],
            },
          ]}
          trigger={
            <Button
              variant="secondary"
              disabled={row.read_only || row.actions.update?.allowed !== true}
              title={row.actions.update?.human ?? undefined}
            >
              Update status
            </Button>
          }
        />
        <PreviewConfirm
          command="delete_external_offer"
          input={{
            external_offer_id: row.id,
            expected_status: row.status as "offered",
            restore: selected,
            reason: "",
            notify: true,
          }}
          title={`Delete ${row.student}'s external offer?`}
          confirmLabel="Delete"
          destructive
          renderSummary={(summary) => (
            <ExternalOfferPlan summary={summary as unknown as Record<string, unknown>} />
          )}
          choices={[{ name: "reason", label: "Reason", kind: "textarea", required: true }]}
          trigger={
            <Button
              variant="destructive-ghost"
              disabled={row.read_only || row.actions.delete?.allowed !== true}
              title={row.actions.delete?.human ?? undefined}
            >
              Delete
            </Button>
          }
        />
      </div>
    </li>
  );
}
