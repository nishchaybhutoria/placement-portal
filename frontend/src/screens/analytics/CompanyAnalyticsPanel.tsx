import type { CompanyAnalytics } from "@/api/payloads";
import { ChartFrame, SPLIT_COLOURS, SeriesBars } from "@/components/charts";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState } from "@/components/ui/states";
import { humanise } from "@/lib/text";
import { CompensationCard, DataTable, PlacedSplit, RateCell } from "@/screens/analytics/parts";

/**
 * ANA-2's company view, across every cycle.
 *
 * It lives inside `staff/company/{id}` rather than on a screen of its own,
 * because LLD §11.3 lists one company screen and because a coordinator looking
 * at a company wants its contacts and its hiring history together.
 */
export function CompanyAnalyticsPanel({ analytics }: { analytics: CompanyAnalytics }) {
  const { totals } = analytics;
  return (
    <div className="flex flex-col gap-gap-lg">
      <div className="grid grid-cols-2 gap-gap-md lg:grid-cols-4">
        <Stat label="Jobs" value={totals.jobs} />
        <Stat label="Cancelled jobs" value={totals.cancelled_jobs} />
        <Stat label="Applicants" value={totals.applicants} />
        <Stat label="Students offered" value={totals.offered} />
      </div>

      <div className="grid gap-gap-md lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Acceptance rate</CardTitle>
          </CardHeader>
          <CardBody className="flex flex-col gap-gap-md">
            <p className="text-headline-md font-semibold">
              <RateCell rate={totals.acceptance_rate} />
            </p>
            {/* Counted in offer rows, not students: a company that extended two
                offers to one person would otherwise get a different number. */}
            <p className="text-body-sm text-muted-foreground">
              {totals.offers_accepted} of {totals.offers_extended} offers extended
              were accepted. Counted per offer, not per student.
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Hired</CardTitle>
          </CardHeader>
          <CardBody>
            <PlacedSplit placed={totals.placed} />
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardBody>
          {analytics.compensation_history.length === 0 ? (
            <EmptyState message="No hiring history yet" />
          ) : (
            <ChartFrame
              title="Compensation history"
              description="One block per cycle this company hired into — years are not pooled, because they are not comparable."
              chart={
                <SeriesBars
                  stacked
                  data={analytics.compensation_history.map((row) => ({
                    label: row.cycle_name,
                    portal: row.placed.split.portal,
                    external: row.placed.split.external,
                  }))}
                  series={[
                    { key: "portal", label: "On campus", colour: SPLIT_COLOURS.portal },
                    { key: "external", label: "External", colour: SPLIT_COLOURS.external },
                  ]}
                />
              }
              table={
                <DataTable
                  headers={["Cycle", "Placed", "Median CTC", "Mean CTC", "With a figure"]}
                  rows={analytics.compensation_history.map((row) => [
                    row.cycle_name,
                    row.placed.total,
                    row.compensation.placement.median ?? "—",
                    row.compensation.placement.mean ?? "—",
                    `${row.compensation.placement.covered}/${row.compensation.placement.placed}`,
                  ])}
                  caption="Compensation by cycle"
                />
              }
            />
          )}
        </CardBody>
      </Card>

      <div className="grid gap-gap-md lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Hires by programme</CardTitle>
          </CardHeader>
          <CardBody>
            {analytics.hires_by_program.length === 0 ? (
              <EmptyState message="No hires yet" />
            ) : (
              <DataTable
                headers={["Programme", "Hires"]}
                rows={analytics.hires_by_program.map((row) => [row.label, row.count])}
                caption="Hires by programme"
              />
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Hires by branch</CardTitle>
          </CardHeader>
          <CardBody>
            {analytics.hires_by_branch.length === 0 ? (
              <EmptyState message="No hires yet" />
            ) : (
              <DataTable
                headers={["Branch", "Hires"]}
                rows={analytics.hires_by_branch.map((row) => [row.label, row.count])}
                caption="Hires by branch"
              />
            )}
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-gap-md lg:grid-cols-2">
        <CompensationCard
          title="Placement CTC (all cycles)"
          block={
            analytics.compensation_history[0]?.compensation.placement ?? {
              unit: "lpa",
              placed: 0,
              covered: 0,
              mean: null,
              median: null,
              min: null,
              max: null,
            }
          }
        />
        <Card>
          <CardHeader>
            <CardTitle>External offers recorded</CardTitle>
          </CardHeader>
          <CardBody>
            {analytics.external_offers.length === 0 ? (
              <EmptyState message="None recorded" />
            ) : (
              <DataTable
                headers={["Status", "Source", "Count"]}
                rows={analytics.external_offers.map((row) => [
                  <StatusChip key={`${row.status}:${row.source}`} domain="external" value={row.status} />,
                  humanise(row.source),
                  row.total,
                ])}
                caption="External offers for this company"
              />
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardBody>
        <p className="text-body-sm text-muted-foreground">{label}</p>
        <p className="tabular text-headline-md font-semibold">{value}</p>
      </CardBody>
    </Card>
  );
}
