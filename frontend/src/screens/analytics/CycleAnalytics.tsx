import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { payload, type BreakdownRow, type CycleAnalyticsPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import {
  CategoryBars,
  ChartFrame,
  FUNNEL_COLOURS,
  SPLIT_COLOURS,
  SeriesBars,
  TrendLines,
} from "@/components/charts";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDate } from "@/lib/date";
import { humanise } from "@/lib/text";
import { ExportButton } from "@/screens/analytics/ExportModal";
import {
  CompensationCard,
  DataTable,
  FunnelCards,
  PlacedSplit,
  PlacementRates,
  RateCell,
} from "@/screens/analytics/parts";

/** ANA-2's cycle dashboard: the funnel and everything that partitions it. */
export function CycleAnalytics() {
  const { id = "" } = useParams();
  const screen = useScreen("staff/cycle/{id}/analytics", { params: { id } });

  if (screen.isPending) return <ScreenSkeleton variant="detail" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<CycleAnalyticsPayload>(screen.data);
  const { funnel, breakdowns } = data;

  const funnelData = [
    { label: "Registered", count: funnel.registered },
    { label: "Applied", count: funnel.applied },
    { label: "Offered", count: funnel.offered },
    { label: "Placed", count: funnel.placed.total },
  ];

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link
            to={`/staff/cycles/${id}`}
            className="inline-flex items-center gap-gap-tight hover:underline"
          >
            <ArrowLeft className="h-3 w-3" /> {data.cycle.name}
          </Link>
        }
        title="Analytics"
        subtitle={`${humanise(data.cycle.kind)} cycle`}
        actions={
          <ExportButton
            cycleId={id}
            kind="cycle_memberships"
            columns={data.export_columns}
            label="Export members"
          />
        }
      />

      <div className="flex flex-col gap-gap-lg">
        <FunnelCards funnel={funnel} />

        <div className="grid gap-gap-md lg:grid-cols-2">
          <PlacementRates funnel={funnel} />
          <Card>
            <CardHeader>
              <CardTitle>Where placements came from</CardTitle>
            </CardHeader>
            <CardBody>
              <PlacedSplit placed={funnel.placed} />
            </CardBody>
          </Card>
        </div>

        <div className="grid gap-gap-md lg:grid-cols-2">
          <CompensationCard title="Placement CTC" block={data.compensation.placement} />
          <CompensationCard
            title="Internship stipend"
            block={data.compensation.internship}
          />
        </div>

        <Card>
          <CardBody>
            <ChartFrame
              title="Funnel"
              description="Registered → applied → offered → placed, on ANA-1's definitions."
              chart={
                <CategoryBars
                  data={funnelData}
                  valueKey="count"
                  colours={[
                    FUNNEL_COLOURS.registered,
                    FUNNEL_COLOURS.applied,
                    FUNNEL_COLOURS.offered,
                    FUNNEL_COLOURS.placed,
                  ]}
                />
              }
              table={
                <DataTable
                  headers={["Stage", "Students"]}
                  rows={funnelData.map((row) => [row.label, row.count])}
                  caption="Funnel counts"
                />
              }
            />
          </CardBody>
        </Card>

        {(["program", "branch", "gender"] as const).map((dimension) => (
          <Card key={dimension}>
            <CardBody>
              <BreakdownPanel
                title={`By ${dimension}`}
                rows={breakdowns[dimension]}
              />
            </CardBody>
          </Card>
        ))}

        <Card>
          <CardBody>
            <ChartFrame
              title="By sector"
              // Sector belongs to the job, not the student, so there is no
              // "registered in a sector" and therefore no rate to show.
              description="Applied, offered and placed. No rate: sector is a property of the job, so there is no registration to divide by."
              chart={
                <SeriesBars
                  data={breakdowns.sector.map((row) => ({
                    label: row.label,
                    applied: row.applied,
                    offered: row.offered,
                    placed: row.placed,
                  }))}
                  series={[
                    { key: "applied", label: "Applied", colour: FUNNEL_COLOURS.applied },
                    { key: "offered", label: "Offered", colour: FUNNEL_COLOURS.offered },
                    { key: "placed", label: "Placed", colour: FUNNEL_COLOURS.placed },
                  ]}
                />
              }
              table={
                <DataTable
                  headers={["Sector", "Applied", "Offered", "Placed"]}
                  rows={breakdowns.sector.map((row) => [
                    row.label,
                    row.applied,
                    row.offered,
                    row.placed,
                  ])}
                  caption="Sector breakdown"
                />
              }
            />
          </CardBody>
        </Card>

        <Card>
          <CardBody>
            {data.timeline.length === 0 ? (
              <EmptyState message="Nothing on the timeline yet. Applications, offers and acceptances appear here as they happen." />
            ) : (
              <ChartFrame
                title="Timeline"
                description="Applications, offers extended, and acceptances per day."
                chart={
                  <TrendLines
                    data={data.timeline.map((row) => ({
                      label: formatDate(row.day),
                      applications: row.applications,
                      offers: row.offers,
                      acceptances: row.acceptances,
                    }))}
                    series={[
                      {
                        key: "applications",
                        label: "Applications",
                        colour: FUNNEL_COLOURS.applied,
                      },
                      { key: "offers", label: "Offers", colour: FUNNEL_COLOURS.offered },
                      {
                        key: "acceptances",
                        label: "Acceptances",
                        colour: FUNNEL_COLOURS.placed,
                      },
                    ]}
                  />
                }
                table={
                  <DataTable
                    headers={["Day", "Applications", "Offers", "Acceptances"]}
                    rows={data.timeline.map((row) => [
                      formatDate(row.day),
                      row.applications,
                      row.offers,
                      row.acceptances,
                    ])}
                    caption="Daily activity"
                  />
                }
              />
            )}
          </CardBody>
        </Card>

        <div className="grid gap-gap-md lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Top companies</CardTitle>
            </CardHeader>
            <CardBody>
              {data.top_companies.length === 0 ? (
                <EmptyState message="No placements yet" />
              ) : (
                <DataTable
                  headers={["Company", "Students placed"]}
                  rows={data.top_companies.map((row) => [
                    <Link
                      key={row.company_id}
                      to={`/staff/companies/${row.company_id}`}
                      className="hover:underline"
                    >
                      {row.name}
                    </Link>,
                    row.placed,
                  ])}
                  caption="Companies ranked by students placed"
                />
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader>
              <CardTitle>Standing</CardTitle>
            </CardHeader>
            <CardBody>
              <DataTable
                headers={["Measure", "Count"]}
                rows={[
                  ["Pending approvals", data.pending_approvals],
                  ["Active strikes", data.discipline.active_strikes],
                  ["Active penalties", data.discipline.active_penalties],
                ]}
                caption="Queue and discipline counts"
              />
            </CardBody>
          </Card>
        </div>
      </div>
    </>
  );
}

function BreakdownPanel({ title, rows }: { title: string; rows: BreakdownRow[] }) {
  return (
    <ChartFrame
      title={title}
      description="Each row is a partition of the funnel above, so the columns sum to it."
      chart={
        <SeriesBars
          stacked
          data={rows.map((row) => ({
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
          headers={[
            "Group",
            "Registered",
            "Applied",
            "Offered",
            "Placed",
            "Placement rate",
          ]}
          rows={rows.map((row) => [
            row.label,
            row.registered,
            row.applied,
            row.offered,
            row.placed,
            <RateCell key={row.key} rate={row.placement_rate} />,
          ])}
          caption={title}
        />
      }
    />
  );
}
