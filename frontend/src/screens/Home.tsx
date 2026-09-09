import { Building2, CalendarRange, ListChecks, Tags } from "lucide-react";
import { Link } from "react-router-dom";

import type { Me } from "@/api/client";
import {
  payload,
  type StaffCyclesPayload,
  type StudentCyclesPayload,
} from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { StudentCycleSections } from "@/components/StudentCycleSections";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui/states";

/**
 * The landing page: whichever cycles this person can act in.
 *
 * Staff and students see different lists because they read different screens —
 * the nav hides links, but what is *on* the page comes from what the server
 * will actually serve to this actor.
 */
export function Home({ me }: { me: Me }) {
  const isStaff = me.user?.role === "admin" || (me.coordinated_cycle_ids?.length ?? 0) > 0;
  return (
    <>
      <PageHeader
        title={`Welcome, ${me.user?.full_name ?? me.user?.email ?? ""}`}
        subtitle="Everything you can reach from here."
      />
      {isStaff ? <StaffHome isAdmin={me.user?.role === "admin"} /> : null}
      {me.user?.role === "admin" ? null : <StudentHome />}
    </>
  );
}

function StaffHome({ isAdmin }: { isAdmin: boolean }) {
  const screen = useScreen("staff/cycles");
  const cycles = screen.data ? payload<StaffCyclesPayload>(screen.data).cycles : [];

  return (
    <section className="flex flex-col gap-gap-lg">
      <h2 className="text-headline-lg text-foreground">Staff</h2>
      <div className="grid gap-gap-lg sm:grid-cols-2 lg:grid-cols-4">
        <Shortcut to="/staff/cycles" icon={<ListChecks className="h-5 w-5" />} label="Cycles" />
        <Shortcut
          to="/staff/companies"
          icon={<Building2 className="h-5 w-5" />}
          label="Companies"
        />
        <Shortcut
          to="/admin/taxonomies"
          icon={<Tags className="h-5 w-5" />}
          label="Taxonomies"
        />
        {!isAdmin ? (
          <Shortcut
            to="/cycles"
            icon={<CalendarRange className="h-5 w-5" />}
            label="Cycles as a student"
          />
        ) : null}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Needs attention</CardTitle>
        </CardHeader>
        {screen.isPending ? (
          <CardBody className="flex flex-col gap-gap-md">
            <Skeleton className="h-8 w-full" />
            <Skeleton className="h-8 w-full" />
          </CardBody>
        ) : screen.isError ? (
          <CardBody>
            <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />
          </CardBody>
        ) : (
          <CardBody className="flex flex-col gap-gap-lg">
            {cycles.filter((cycle) => cycle.pending_count > 0).length === 0 ? (
              <EmptyState message="No cycle has membership requests waiting." />
            ) : (
              cycles
                .filter((cycle) => cycle.pending_count > 0)
                .map((cycle) => (
                  <div
                    key={cycle.id}
                    className="flex items-center justify-between gap-gap-lg"
                  >
                    <Link
                      to={`/staff/cycles/${cycle.id}/approvals`}
                      className="text-body-md text-accent hover:underline"
                    >
                      {cycle.name}
                    </Link>
                    <span className="tabular text-body-md text-foreground">
                      {cycle.pending_count} waiting
                    </span>
                  </div>
                ))
            )}
          </CardBody>
        )}
      </Card>
    </section>
  );
}

function StudentHome() {
  const screen = useScreen("cycles/joinable");

  if (screen.isPending) {
    return (
      <section className="flex flex-col gap-gap-lg">
        <h2 className="text-headline-lg text-foreground">Your cycles</h2>
        <Skeleton className="h-32 w-full" />
      </section>
    );
  }
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<StudentCyclesPayload>(screen.data);
  return (
    <StudentCycleSections
      cycles={data.cycles}
      enrollmentId={data.enrollment_id}
      resumes={data.resumes}
    />
  );
}

function Shortcut({
  to,
  icon,
  label,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <Link
      to={to}
      className="flex items-center gap-gap-md rounded border border-border bg-card p-gap-lg text-body-md text-foreground transition-colors hover:bg-muted"
    >
      <span className="text-muted-foreground">{icon}</span>
      {label}
    </Link>
  );
}
