import { Link } from "react-router-dom";

import { payload, type DashboardPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { OfferActionPlan } from "@/components/CommandSummaryDetails";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusChip } from "@/components/ui/statusChip";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDateTime, formatZonedDateTime } from "@/lib/date";
import { counted, humanise } from "@/lib/text";

export function Dashboard() {
  const screen = useScreen("me/dashboard");
  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }
  const data = payload<DashboardPayload>(screen.data);
  return (
    <>
      <PageHeader title="Dashboard" subtitle="Offers, upcoming rounds, and your current record." />
      <OfferCards data={data} />
      <ApplicationStatuses applications={data.applications} />
      <Card>
        <CardHeader><CardTitle>External offers (read only)</CardTitle></CardHeader>
        <CardBody>
          {data.external_offers.length === 0 ? (
            <EmptyState message="No PPO or off-campus offer is recorded." />
          ) : (
            <ul className="flex flex-col gap-gap-md">
              {data.external_offers.map((row) => (
                <li key={row.id} className="flex flex-wrap items-center gap-gap-md rounded border border-border p-gap-lg">
                  <div className="min-w-0 flex-1">
                    <p className="text-body-md font-medium text-foreground">{row.company.name}</p>
                    <p className="text-body-sm text-muted-foreground">
                      {humanise(row.source)} · {humanise(row.outcome)}
                      {row.attached_cycle ? ` · ${row.attached_cycle.name}` : ""}
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
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
      <div className="grid gap-gap-lg lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Upcoming rounds</CardTitle></CardHeader>
          <CardBody>
            {data.upcoming_rounds.length === 0 ? (
              <EmptyState message="No upcoming round is scheduled." />
            ) : (
              <ul className="flex flex-col gap-gap-md">
                {data.upcoming_rounds.map((row) => (
                  <li key={`${row.application_id}-${row.round}`} className="text-body-md">
                    <strong>{row.job}</strong> · {row.round}
                    <span className="block text-body-sm text-muted-foreground">
                      {[row.venue, row.scheduled_at ? formatZonedDateTime(row.scheduled_at) : null].filter(Boolean).join(" · ") || "Timing not published"}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader><CardTitle>Your record</CardTitle></CardHeader>
          <CardBody className="flex flex-col gap-gap-md text-body-md">
            <p>{counted(data.memberships.filter((row) => row.status === "active").length, "active membership")}</p>
            <p>{counted(data.applications.length, "application")}</p>
            <p>
              {counted(data.discipline.active_strikes, "active strike")} ·{" "}
              {counted(data.discipline.active_penalties, "active penalty")}
            </p>
            <Button variant="link" asChild><Link to="/applications">View application history</Link></Button>
          </CardBody>
        </Card>
      </div>
    </>
  );
}

function ApplicationStatuses({
  applications,
}: {
  applications: DashboardPayload["applications"];
}) {
  return (
    <Card>
      <CardHeader><CardTitle>Application status</CardTitle></CardHeader>
      <CardBody>
        {applications.length === 0 ? (
          <EmptyState message="You have not applied to anything yet." />
        ) : (
          <ul className="flex flex-col gap-gap-md">
            {applications.map((application) => (
              <li
                key={application.id}
                className="flex flex-wrap items-center gap-gap-md rounded border border-border p-gap-lg"
              >
                <div className="min-w-0 flex-1">
                  <p className="text-body-md font-medium text-foreground">{application.job}</p>
                  <p className="text-body-sm text-muted-foreground">
                    {application.company} · {application.cycle}
                  </p>
                </div>
                <StatusChip domain="application" value={application.status} />
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function OfferCards({ data }: { data: DashboardPayload }) {
  const current = data.offers.filter((row) => row.status === "offered" && !row.response && !row.terminated);
  return (
    <Card>
      <CardHeader><CardTitle>Offers awaiting your response ({current.length})</CardTitle></CardHeader>
      <CardBody>
        {current.length === 0 ? (
          <EmptyState message="You have no offer awaiting a response." />
        ) : (
          <ul className="flex flex-col gap-gap-md">
            {current.map((row) => (
              <li key={row.offer_id} className="flex flex-wrap items-center gap-gap-md rounded border border-border p-gap-lg">
                <div className="min-w-0 flex-1">
                  <Link to={`/jobs/${row.job_id}`} className="text-body-md font-medium text-accent hover:underline">{row.job}</Link>
                  <p className="text-body-sm text-muted-foreground">{row.company} · {row.cycle}</p>
                  {row.deadline_at ? <p className="text-body-sm text-muted-foreground">Respond by {formatDateTime(row.deadline_at)}</p> : null}
                </div>
                <PreviewConfirm
                  command="accept_offer"
                  input={{
                    cycle_id: row.cycle_id,
                    job_id: row.job_id,
                    application_id: row.application_id,
                    offer_id: row.offer_id,
                    enrollment_id: data.enrollment_id,
                    expected_status: "offered",
                  }}
                  title={`Accept ${row.job}?`}
                  confirmLabel="Accept offer"
                  renderSummary={(summary) => (
                    <OfferActionPlan summary={summary as unknown as Record<string, unknown>} />
                  )}
                  trigger={<Button disabled={!row.actions.accept.allowed} title={row.actions.accept.human ?? undefined}>Accept</Button>}
                />
                <PreviewConfirm
                  command="decline_offer"
                  input={{
                    cycle_id: row.cycle_id,
                    job_id: row.job_id,
                    application_id: row.application_id,
                    offer_id: row.offer_id,
                    enrollment_id: data.enrollment_id,
                    expected_status: "offered",
                  }}
                  title={`Decline ${row.job}?`}
                  confirmLabel="Decline offer"
                  destructive
                  renderSummary={(summary) => (
                    <OfferActionPlan summary={summary as unknown as Record<string, unknown>} />
                  )}
                  trigger={<Button variant="destructive-ghost" disabled={!row.actions.decline.allowed} title={row.actions.decline.human ?? undefined}>Decline</Button>}
                />
              </li>
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}
