import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { payload, type JobAnalyticsPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { ChartFrame, FUNNEL_COLOURS, SeriesBars } from "@/components/charts";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { ExportButton } from "@/screens/analytics/ExportModal";
import { CompensationCard, DataTable, RateCell } from "@/screens/analytics/parts";

/**
 * ANA-2's job page.
 *
 * A dedicated-cycle job gets the per-round pipeline; an open-cycle job gets
 * applied → offered → accepted and no round columns at all, because it records
 * outcomes directly and has no pipeline to report. Showing empty round columns
 * for one would invent a process that does not exist.
 */
export function JobAnalytics() {
  const { id = "" } = useParams();
  const screen = useScreen("staff/job/{id}/analytics", { params: { id } });

  if (screen.isPending) return <ScreenSkeleton variant="detail" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<JobAnalyticsPayload>(screen.data);
  const funnelData = [
    { label: "Applied", count: data.funnel.applied },
    { label: "Offered", count: data.funnel.offered },
    { label: "Accepted", count: data.funnel.accepted },
  ];

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link
            to={`/staff/jobs/${id}/board`}
            className="inline-flex items-center gap-gap-tight hover:underline"
          >
            <ArrowLeft className="h-3 w-3" /> {data.job.title}
          </Link>
        }
        title="Analytics"
        subtitle={`${data.job.company.name} · ${data.job.cycle.name}`}
        actions={
          <ExportButton
            cycleId={data.job.cycle.id}
            jobId={data.job.id}
            kind="job_applications"
            columns={data.export_columns}
            label="Export applicants"
          />
        }
      />

      <div className="flex flex-col gap-gap-lg">
        <div className="grid grid-cols-2 gap-gap-md lg:grid-cols-4">
          <Stat label="Applied" value={data.funnel.applied} />
          <Stat label="Offered" value={data.funnel.offered} />
          <Stat label="Accepted" value={data.funnel.accepted} />
          <Card>
            <CardBody>
              <p className="text-body-sm text-muted-foreground">Offer conversion</p>
              <p className="text-body-md font-semibold">
                <RateCell rate={data.funnel.offer_conversion} />
              </p>
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardBody>
            <ChartFrame
              title="Applied → offered → accepted"
              chart={
                <SeriesBars
                  data={funnelData.map((row) => ({ label: row.label, count: row.count }))}
                  series={[
                    { key: "count", label: "Students", colour: FUNNEL_COLOURS.offered },
                  ]}
                />
              }
              table={
                <DataTable
                  headers={["Stage", "Students"]}
                  rows={funnelData.map((row) => [row.label, row.count])}
                  caption="Job funnel"
                />
              }
            />
          </CardBody>
        </Card>

        {data.shape === "pipeline" ? (
          <Card>
            <CardBody>
              {data.rounds.length === 0 ? (
                <EmptyState message="No rounds yet. Add rounds in the builder to see the pipeline here." />
              ) : (
                <ChartFrame
                  title="Per round"
                  description="Entered, advanced, eliminated and waitlisted, with attendance beside them."
                  chart={
                    <SeriesBars
                      stacked
                      data={data.rounds.map((round) => ({
                        label: round.name,
                        advanced: round.advanced,
                        eliminated: round.eliminated,
                        waitlisted: round.waitlisted,
                        pending: round.pending,
                      }))}
                      series={[
                        { key: "advanced", label: "Advanced", colour: FUNNEL_COLOURS.placed },
                        { key: "eliminated", label: "Eliminated", colour: "hsl(var(--danger))" },
                        { key: "waitlisted", label: "Waitlisted", colour: FUNNEL_COLOURS.offered },
                        { key: "pending", label: "Pending", colour: FUNNEL_COLOURS.registered },
                      ]}
                    />
                  }
                  table={
                    <DataTable
                      headers={[
                        "Round",
                        "Entered",
                        "Advanced",
                        "Eliminated",
                        "Waitlisted",
                        "Absent",
                        // RND-3 gives excused and absent different
                        // consequences, so they are never one column.
                        "Excused",
                        "Conversion",
                        "Median hours in round",
                      ]}
                      rows={data.rounds.map((round) => [
                        round.name,
                        round.entered,
                        round.advanced,
                        round.eliminated,
                        round.waitlisted,
                        round.absent,
                        round.excused,
                        <RateCell key={round.round_id} rate={round.conversion} />,
                        round.median_hours ?? "—",
                      ])}
                      caption="Round pipeline"
                    />
                  }
                />
              )}
            </CardBody>
          </Card>
        ) : (
          <Card>
            <CardHeader>
              <CardTitle>Open cycle</CardTitle>
            </CardHeader>
            <CardBody>
              <p className="text-body-sm text-muted-foreground">
                This job belongs to an open cycle, where outcomes are recorded
                directly rather than run through rounds, so there is no pipeline
                to report.
              </p>
            </CardBody>
          </Card>
        )}

        <div className="grid gap-gap-md lg:grid-cols-2">
          <CompensationCard title="Placement CTC" block={data.compensation.placement} />
          <CompensationCard
            title="Internship stipend"
            block={data.compensation.internship}
          />
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Applications by status</CardTitle>
          </CardHeader>
          <CardBody>
            <DataTable
              headers={["Status", "Applications"]}
              rows={Object.entries(data.statuses).map(([status, count]) => [
                <StatusChip key={status} domain="application" value={status} />,
                count,
              ])}
              caption="Application statuses"
            />
          </CardBody>
        </Card>
      </div>
    </>
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
