import { payload, type MyNotificationsPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardBody } from "@/components/ui/card";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { StatusChip } from "@/components/ui/statusChip";
import { DataTable, type Column } from "@/components/ui/table";
import { formatZonedDateTime } from "@/lib/date";
import { counted, humanise } from "@/lib/text";

type Row = MyNotificationsPayload["notifications"][number];

/**
 * Everything the portal has sent this address (LLD §18, deferred until now).
 *
 * A record, not a second renderer. The subject is shown and the body is not:
 * the body was rendered at delivery from a template an operator may since have
 * edited, so re-rendering it here could state, in the student's own record,
 * something other than what they were sent. If they need the body they have
 * the email; what they cannot otherwise recover is *whether it was sent at
 * all*, which is exactly the question that brings someone to the CDS office.
 *
 * A queued or failed notice is listed too. A student watching for a schedule
 * that has not arrived is the person this screen is for, and hiding the row
 * until delivery succeeds would answer their question with silence.
 */
export function MyNotifications() {
  const screen = useScreen("me/notifications");

  if (screen.isPending) return <ScreenSkeleton variant="table" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<MyNotificationsPayload>(screen.data);
  const rows = data.notifications;

  const columns: Column<Row>[] = [
    {
      key: "subject",
      header: "Subject",
      cell: (row) => (
        <div>
          <p className="text-body-md text-foreground">{row.subject}</p>
          <p className="text-body-sm text-muted-foreground">{humanise(row.event_key)}</p>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (row) => <StatusChip domain="notification" value={row.status} />,
    },
    {
      key: "sent",
      header: "Sent",
      cell: (row) =>
        row.sent_at ? (
          formatZonedDateTime(row.sent_at)
        ) : (
          <span className="text-muted-foreground">
            Not yet — recorded {formatZonedDateTime(row.recorded_at)}
          </span>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle={
          rows.length === 0
            ? "Everything the portal has emailed you will appear here."
            : `${counted(rows.length, "notice")} sent to your institute address.`
        }
      />
      {rows.length === 0 ? (
        <EmptyState message="The portal has not emailed you yet." />
      ) : (
        <Card>
          <CardBody className="p-0">
            <DataTable
              rows={rows}
              columns={columns}
              rowKey={(row) => row.id}
            />
          </CardBody>
        </Card>
      )}
    </>
  );
}
