import { payload, type PortalAnalyticsPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { ChartFrame, FUNNEL_COLOURS, SPLIT_COLOURS, SeriesBars, TrendLines } from "@/components/charts";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDate } from "@/lib/date";
import { counted } from "@/lib/text";
import { DataTable, PlacedSplit, PlacementRates, RateCell } from "@/screens/analytics/parts";

/** ANA-2's portal dashboard: multi-cycle trends in the ANA-1 vocabulary. */
export function PortalAnalytics() {
  const screen = useScreen("admin/analytics/portal", {});

  if (screen.isPending) return <ScreenSkeleton variant="detail" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<PortalAnalyticsPayload>(screen.data);
  const trend = data.years.map((year) => ({
    label: year.year,
    registered: year.registered,
    applied: year.applied,
    offered: year.offered,
    placed: year.placed.total,
  }));

  return (
    <>
      <PageHeader
        title="Portal analytics"
        subtitle="Every cycle, in one vocabulary"
      />

      <div className="flex flex-col gap-gap-lg">
        <div className="grid gap-gap-md lg:grid-cols-2">
          <PlacementRates funnel={data.overall} />
          <Card>
            <CardHeader>
              <CardTitle>Placed across the portal</CardTitle>
            </CardHeader>
            <CardBody className="flex flex-col gap-gap-md">
              <PlacedSplit placed={data.overall.placed} />
              <p className="text-body-sm text-muted-foreground">
                Counting every acceptance regardless of attachment — the DER-1
                dimensions — {counted(data.portal_wide_placed.total, "student")} {data.portal_wide_placed.total === 1 ? "is" : "are"} placed,{" "}
                {data.portal_wide_placed.split.external} of them externally.
              </p>
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardBody>
            {trend.length === 0 ? (
              <EmptyState message="No cycles yet" />
            ) : (
              <ChartFrame
                title="Year on year"
                description="Cycles are grouped by the year they start in; a cycle with no start date is shown as undated."
                chart={
                  <TrendLines
                    data={trend}
                    series={[
                      { key: "registered", label: "Registered", colour: FUNNEL_COLOURS.registered },
                      { key: "applied", label: "Applied", colour: FUNNEL_COLOURS.applied },
                      { key: "offered", label: "Offered", colour: FUNNEL_COLOURS.offered },
                      { key: "placed", label: "Placed", colour: FUNNEL_COLOURS.placed },
                    ]}
                  />
                }
                table={
                  <DataTable
                    headers={[
                      "Year",
                      "Cycles",
                      "Registered",
                      "Applied",
                      "Offered",
                      "Placed",
                      "On campus",
                      "External",
                      "Placement rate",
                      "Median CTC",
                    ]}
                    rows={data.years.map((year) => [
                      year.year,
                      year.cycle_count,
                      year.registered,
                      year.applied,
                      year.offered,
                      year.placed.total,
                      year.placed.split.portal,
                      year.placed.split.external,
                      <RateCell key={year.year} rate={year.placement_rate} />,
                      year.compensation.placement.median ?? "—",
                    ])}
                    caption="Yearly trend"
                  />
                }
              />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardBody>
            <ChartFrame
              title="Programme mix"
              chart={
                <SeriesBars
                  stacked
                  data={data.program_mix.map((row) => ({
                    label: row.label,
                    portal: row.placed_split.portal ?? 0,
                    external:
                      (row.placed_split.ppo ?? 0) +
                      (row.placed_split.off_campus ?? 0) +
                      (row.placed_split.other ?? 0),
                  }))}
                  series={[
                    { key: "portal", label: "On campus", colour: SPLIT_COLOURS.portal },
                    { key: "external", label: "External", colour: SPLIT_COLOURS.external },
                  ]}
                />
              }
              table={
                <DataTable
                  headers={["Programme", "Registered", "Placed", "Placement rate"]}
                  rows={data.program_mix.map((row) => [
                    row.label,
                    row.registered,
                    row.placed,
                    <RateCell key={row.key} rate={row.placement_rate} />,
                  ])}
                  caption="Programme mix"
                />
              }
            />
          </CardBody>
        </Card>

        <CannedReportCard report={data.canned_report} />

        <Card>
          <CardHeader>
            <CardTitle>Participation</CardTitle>
          </CardHeader>
          <CardBody>
            <DataTable
              headers={["Cycle", "Kind", "Starts"]}
              rows={data.participation.map((cycle) => [
                cycle.name,
                cycle.kind,
                cycle.starts_on ? formatDate(cycle.starts_on) : "—",
              ])}
              caption="Cycles on the portal"
            />
          </CardBody>
        </Card>
      </div>
    </>
  );
}

/**
 * ANA-3's canned report.
 *
 * Rendered straight from the server's column list rather than a layout written
 * here, so the table on this page and the spreadsheet the office exports are
 * the same table. The provisional notice is not dismissible: it is the part
 * that stops these columns being filed as though somebody had agreed them.
 */
function CannedReportCard({ report }: { report: PortalAnalyticsPayload["canned_report"] }) {
  const cell = (row: Record<string, unknown>, key: string) => {
    const value = row[key];
    if (value !== null && typeof value === "object" && "ratio" in value) {
      const rate = value as { ratio: string | null; numerator: number; denominator: number };
      return rate.ratio === null ? "—" : `${(Number(rate.ratio) * 100).toFixed(1)}%`;
    }
    return value === null || value === undefined ? "—" : String(value);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Per-batch report</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-md">
        {report.provisional ? (
          <p className="rounded border border-warning-border bg-warning-subtle p-3 text-body-sm text-warning">
            {report.note}
          </p>
        ) : null}
        <div className="overflow-x-auto">
          <DataTable
            headers={report.columns.map((column) => column.label)}
            rows={[...report.rows, report.total].map((row) =>
              report.columns.map((column) => cell(row, column.key)),
            )}
            caption="Per-batch, per-programme outcomes"
          />
        </div>
      </CardBody>
    </Card>
  );
}
