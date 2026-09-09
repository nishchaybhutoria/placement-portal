import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import { payload, type ExternalOfferScreenRow, type StaffCycleExternalPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { BulkBar } from "@/components/BulkBar";
import { BulkRows, type BulkRow } from "@/components/BulkRows";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { newIdempotencyKey } from "@/lib/idempotency";
import { humanise } from "@/lib/text";

export function CycleExternal() {
  const { id = "" } = useParams();
  const screen = useScreen("staff/cycle/{id}/external", { params: { id } });
  const [selected, setSelected] = useState<string[]>([]);
  const batchKey = useMemo(() => newIdempotencyKey(), [selected.join(",")]);

  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }
  const data = payload<StaffCycleExternalPayload>(screen.data);
  return (
    <>
      <PageHeader
        title={`${data.cycle.name} external offers`}
        subtitle={
          data.policy.max_accepted_offers === null
            ? "This cycle has no accepted-offer cap."
            : `Accepted-offer cap: ${data.policy.max_accepted_offers}`
        }
      />
      {!data.cycle.archived ? (
        <BulkBar
          selected={selected}
          onChange={setSelected}
          identifierLabel="external offer ids"
          actions={
            <PreviewConfirm
              command="attach_external_offers"
              input={{
                cycle_id: data.cycle.id,
                rows: selected.map((external_offer_id) => ({ external_offer_id })),
                batch_key: batchKey,
                reason: "",
              }}
              title={`Attach ${selected.length} external offer${selected.length === 1 ? "" : "s"}?`}
              confirmLabel="Attach selected"
              choices={[{ name: "reason", label: "Reason", kind: "textarea", required: true }]}
              renderSummary={(summary) => (
                <BulkRows
                  summary={summary as never}
                  applyLabel="Will be attached"
                  // The command reports the external-offer id it was sent; the
                  // pool on screen is where the student's name is.
                  resolveName={(row: BulkRow) => {
                    const match = [...data.unattached_pool, ...data.attached].find(
                      (candidate) => candidate.id === row.external_offer_id,
                    );
                    return match
                      ? `${match.student} — ${match.company.name}`
                      : undefined;
                  }}
                />
              )}
              trigger={<Button disabled={selected.length === 0}>Attach selected</Button>}
              onDone={() => setSelected([])}
            />
          }
        />
      ) : null}
      <OfferSection title="Attached" rows={data.attached} cycleId={data.cycle.id} />
      <OfferSection
        title="Matching unattached pool"
        rows={data.unattached_pool}
        cycleId={data.cycle.id}
        selected={selected}
        onSelect={(offerId, checked) =>
          setSelected((current) =>
            checked ? [...current, offerId] : current.filter((item) => item !== offerId),
          )
        }
      />
    </>
  );
}

function OfferSection({
  title,
  rows,
  cycleId,
  selected = [],
  onSelect,
}: {
  title: string;
  rows: ExternalOfferScreenRow[];
  cycleId: string;
  selected?: string[];
  onSelect?: (offerId: string, checked: boolean) => void;
}) {
  return (
    <Card>
      <CardHeader><CardTitle>{title} ({rows.length})</CardTitle></CardHeader>
      <CardBody>
        {rows.length === 0 ? (
          <EmptyState message={`No offers in ${title.toLowerCase()}.`} />
        ) : (
          <ul className="flex flex-col gap-gap-md">
            {rows.map((row) => (
              <li key={row.id} className="flex flex-wrap items-center gap-gap-md rounded border border-border p-gap-lg">
                {onSelect && row.actions.attach?.allowed ? (
                  <Checkbox
                    checked={selected.includes(row.id)}
                    onChange={(event) => onSelect(row.id, event.target.checked)}
                    aria-label={`Select ${row.student} at ${row.company.name}`}
                  />
                ) : null}
                <div className="min-w-0 flex-1">
                  <p className="text-body-md font-medium text-foreground">{row.student}</p>
                  <p className="text-body-sm text-muted-foreground">
                    {row.company.name} · {humanise(row.outcome)} · {humanise(row.source)}
                  </p>
                  <p className="text-body-sm text-muted-foreground">
                    {row.ctc_lpa
                      ? `${row.ctc_lpa} LPA`
                      : row.stipend_month
                        ? `${row.stipend_month} INR/month`
                        : "Compensation not recorded"}
                  </p>
                </div>
                <StatusChip domain="external" value={row.status} />
                {row.actions.attach ? (
                  <PreviewConfirm
                    command="attach_external_offer"
                    input={{
                      cycle_id: cycleId,
                      external_offer_id: row.id,
                      expected_attached_cycle_id: null,
                      reason: "",
                    }}
                    title={`Attach ${row.student}'s offer?`}
                    confirmLabel="Attach"
                    choices={[{ name: "reason", label: "Reason", kind: "textarea", required: true }]}
                    trigger={
                      <Button variant="secondary" disabled={!row.actions.attach.allowed} title={row.actions.attach.human ?? undefined}>
                        Attach
                      </Button>
                    }
                  />
                ) : null}
                {row.actions.detach ? (
                  <PreviewConfirm
                    command="detach_external_offer"
                    input={{
                      cycle_id: cycleId,
                      external_offer_id: row.id,
                      expected_attached_cycle_id: cycleId,
                      reason: "",
                    }}
                    title={`Detach ${row.student}'s offer?`}
                    description="Any auto-created membership remains active."
                    confirmLabel="Detach"
                    destructive
                    choices={[{ name: "reason", label: "Reason", kind: "textarea", required: true }]}
                    trigger={
                      <Button variant="destructive-ghost" disabled={!row.actions.detach.allowed} title={row.actions.detach.human ?? undefined}>
                        Detach
                      </Button>
                    }
                  />
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
