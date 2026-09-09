import { StatusChip } from "@/components/ui/statusChip";

function words(value: unknown): string {
  return String(value ?? "not recorded").replace(/_/g, " ");
}

function rows(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value)
    ? value.filter((row): row is Record<string, unknown> =>
        typeof row === "object" && row !== null && !Array.isArray(row),
      )
    : [];
}

function Section({
  title,
  entries,
  empty,
  render,
}: {
  title: string;
  entries: Record<string, unknown>[];
  empty: string;
  render: (row: Record<string, unknown>, index: number) => React.ReactNode;
}) {
  return (
    <section>
      <p className="text-label-caps uppercase text-muted-foreground">
        <span>{title}</span> ({entries.length})
      </p>
      {entries.length === 0 ? (
        <p className="mt-gap-tight text-body-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="mt-gap-tight flex flex-col gap-gap-tight text-body-sm text-foreground">
          {entries.map((entry, index) => (
            <li key={String(entry.application_id ?? entry.round_id ?? entry.effect ?? index)}>
              {render(entry, index)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

/** INT-1's round-state repair preview. These records are not bulk result rows. */
export function ReinstatementPlan({ summary }: { summary: Record<string, unknown> }) {
  const stateSection = (title: string, value: unknown, empty: string) => (
    <Section
      title={title}
      entries={rows(value)}
      empty={empty}
      render={(row) => (
        <>
          <span className="font-medium">{words(row.round_name)}</span>
          {" · result: "}{words(row.result)}
          {" · attendance: "}{words(row.attendance)}
        </>
      )}
    />
  );

  return (
    <div className="flex flex-col gap-gap-lg">
      {stateSection(
        "Round states cleared",
        summary.cleared_round_states,
        "No later round states will be cleared.",
      )}
      {stateSection(
        "Round states kept",
        summary.kept_round_states,
        "No earlier round states are present.",
      )}
    </div>
  );
}

/** CYC-4's application cascade when a membership exits. */
export function MembershipExitPlan({ summary }: { summary: Record<string, unknown> }) {
  return (
    <div className="flex flex-col gap-gap-lg">
      <Section
        title="Will auto-withdraw"
        entries={rows(summary.auto_withdrawn)}
        empty="No live applications will be auto-withdrawn."
        render={(row) => (
          <>
            <span className="font-medium">{words(row.job)}</span>
            {" · from "}{words(row.from_status)}
          </>
        )}
      />
      <Section
        title="Will remain untouched"
        entries={rows(summary.untouched)}
        empty="No offered or accepted applications will remain behind."
        render={(row) => (
          <>
            <span className="font-medium">{words(row.job)}</span>
            {" · "}{words(row.status)}
            {row.suggested_command ? ` · use ${words(row.suggested_command)}` : ""}
          </>
        )}
      />
    </div>
  );
}

/** OFR-3's cross-application consequences of accepting an offer. */
export function OfferActionPlan({ summary }: { summary: Record<string, unknown> }) {
  const cascade = rows(summary.cascade);
  const overrideCount = Array.isArray(summary.applied_override_ids)
    ? summary.applied_override_ids.length
    : 0;
  return (
    <div className="flex flex-col gap-gap-lg">
      <p className="text-body-md text-foreground">
        This application will become <strong>{words(summary.status)}</strong>.
      </p>
      <Section
        title="Other applications affected"
        entries={cascade}
        empty="No other applications will change."
        render={(row) => (
          <>
            <span className="font-medium">{words(row.job)}</span>
            {row.company ? ` · ${words(row.company)}` : ""}
            {row.cycle ? ` · ${words(row.cycle)}` : ""}
            {" · "}{words(row.from_status)} → {words(row.to_status)}
          </>
        )}
      />
      {overrideCount > 0 ? (
        <p className="text-body-sm text-muted-foreground">
          {overrideCount} applicable override{overrideCount === 1 ? " was" : "s were"} credited.
        </p>
      ) : null}
    </div>
  );
}

interface RestorationCandidate extends Record<string, unknown> {
  application_id?: string;
  job?: string;
  selected?: boolean;
}

function RestorationDecisions({ candidates }: { candidates: RestorationCandidate[] }) {
  return (
    <Section
      title="Restoration decisions"
      entries={candidates}
      empty="No applications are eligible for restoration."
      render={(row) => (
        <>
          <span className="font-medium">
            {row.selected ? "Restore" : "Leave"} {words(row.job)}
          </span>
          {" · "}{words(row.current_status)} → {words(row.restore_status)}
          {row.target_round_id ? " · prior round restored" : " · no round"}
          {row.requires_fresh_offer ? " · fresh offer" : ""}
          {row.deadline_at ? ` · deadline ${words(row.deadline_at)}` : ""}
          {row.can_restore === false && row.blocked_reason
            ? ` · blocked: ${words(row.blocked_reason)}`
            : ""}
        </>
      )}
    />
  );
}

function RestoredApplications({
  restored,
  candidates,
}: {
  restored: Record<string, unknown>[];
  candidates: RestorationCandidate[];
}) {
  const names = new Map(candidates.map((row) => [row.application_id, row.job]));
  return (
    <Section
      title="Will restore"
      entries={restored}
      empty="No applications will be restored."
      render={(row) => (
        <>
          <span className="font-medium">
            {words(names.get(String(row.application_id)) ?? row.application_id)}
          </span>
          {" · "}<StatusChip domain="application" value={words(row.status)} />
          {row.target_round_id ? " · prior round restored" : " · no round"}
          {row.fresh_offer_id ? " · fresh offer" : ""}
          {row.deadline_at ? ` · deadline ${words(row.deadline_at)}` : ""}
        </>
      )}
    />
  );
}

/** OFR-5's complete termination plan, including every restoration candidate. */
export function TerminationPlan({ summary }: { summary: Record<string, unknown> }) {
  const candidates = rows(summary.restoration_candidates) as RestorationCandidate[];
  return (
    <div className="flex flex-col gap-gap-lg">
      <Section
        title="Automatic effects"
        entries={rows(summary.automatic_effects)}
        empty="No automatic effects."
        render={(row) => (
          <>
            {words(row.effect)}
            {row.applies === false ? " (not applicable)" : ""}
          </>
        )}
      />
      <RestorationDecisions candidates={candidates} />
      <RestoredApplications restored={rows(summary.restored)} candidates={candidates} />
    </div>
  );
}

/** EXT-1's effects, acceptance cascade, and optional compensating restorations. */
export function ExternalOfferPlan({ summary }: { summary: Record<string, unknown> }) {
  const candidates = rows(summary.restoration_candidates) as RestorationCandidate[];
  return (
    <div className="flex flex-col gap-gap-lg">
      <Section
        title="Automatic effects"
        entries={rows(summary.automatic_effects)}
        empty="No automatic effects."
        render={(row) => (
          <>
            {words(row.effect)}
            {row.applies === false ? " (not applicable)" : ""}
          </>
        )}
      />
      <Section
        title="Other applications affected"
        entries={rows(summary.cascade)}
        empty="No other applications will change."
        render={(row) => (
          <>
            <span className="font-medium">{words(row.job)}</span>
            {row.company ? ` · ${words(row.company)}` : ""}
            {row.cycle ? ` · ${words(row.cycle)}` : ""}
            {" · "}{words(row.from_status)} → {words(row.to_status)}
          </>
        )}
      />
      <RestorationDecisions candidates={candidates} />
      <RestoredApplications restored={rows(summary.restored)} candidates={candidates} />
    </div>
  );
}

/** A compact field-name list for command launchers without profile metadata. */
export function ChangedFieldsPlan({ summary }: { summary: Record<string, unknown> }) {
  const fields = Array.isArray(summary.changed_fields) ? summary.changed_fields : [];
  return fields.length === 0 ? (
    <p className="text-body-md text-muted-foreground">Nothing changes.</p>
  ) : (
    <ul className="flex flex-col gap-gap-tight text-body-md text-foreground">
      {fields.map((field) => <li key={String(field)}>{words(field)} changes</li>)}
    </ul>
  );
}
