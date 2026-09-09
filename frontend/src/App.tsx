import { QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy, useState } from "react";
import { Navigate, Route, Routes } from "react-router-dom";

import { createQueryClient } from "@/api/queryClient";
import { AppLayout } from "@/components/AppLayout";
import { AuthGate } from "@/components/AuthGate";
import { Skeleton } from "@/components/ui/states";
import { Home } from "@/screens/Home";
import { BulkUpsert } from "@/screens/admin/BulkUpsert";
import { Discipline } from "@/screens/admin/Discipline";
import { Findings } from "@/screens/admin/Findings";
import { Overrides } from "@/screens/admin/Overrides";
import { Settings } from "@/screens/admin/Settings";
import { Taxonomies } from "@/screens/admin/Taxonomies";
import { Templates } from "@/screens/admin/Templates";
import { Users } from "@/screens/admin/Users";
import { Companies } from "@/screens/companies/Companies";
import { Company } from "@/screens/companies/Company";
import { Approvals } from "@/screens/cycles/Approvals";
import { StaffCycle } from "@/screens/cycles/StaffCycle";
import { StaffCycles } from "@/screens/cycles/StaffCycles";
import { CycleJobs } from "@/screens/jobs/CycleJobs";
import { JobBoard } from "@/screens/jobs/JobBoard";
import { JobBuilder } from "@/screens/jobs/JobBuilder";
import { CycleExternal } from "@/screens/offers/CycleExternal";
import { ExternalOffers } from "@/screens/offers/ExternalOffers";
import { Offers } from "@/screens/offers/Offers";
import { Dashboard } from "@/screens/student/Dashboard";
import { MyApplications } from "@/screens/student/MyApplications";
import { MyNotifications } from "@/screens/student/MyNotifications";
import { Profile } from "@/screens/student/Profile";
import { StudentCycles } from "@/screens/student/StudentCycles";
import { StudentJob } from "@/screens/student/StudentJob";
import { StudentJobs } from "@/screens/student/StudentJobs";
import { StudentRecord } from "@/screens/student/StudentRecord";

/*
 * The analytics screens are loaded on demand.
 *
 * They are the only part of the app that pulls in a charting library, and they
 * are staff- and admin-only; a student who will never open one should not
 * download it on every visit. Splitting here keeps the shared bundle roughly
 * where it was before M15 and puts the charting weight behind the three routes
 * that actually draw charts.
 */
const CycleAnalytics = lazy(() =>
  import("@/screens/analytics/CycleAnalytics").then((m) => ({ default: m.CycleAnalytics })),
);
const JobAnalytics = lazy(() =>
  import("@/screens/analytics/JobAnalytics").then((m) => ({ default: m.JobAnalytics })),
);
const PortalAnalytics = lazy(() =>
  import("@/screens/analytics/PortalAnalytics").then((m) => ({ default: m.PortalAnalytics })),
);

/**
 * Routes for the screens that exist (M0–M15).
 *
 * Nothing here is a mock: every route reads a real screen. Authorisation is
 * the server's — a route hidden from the nav is
 * still reachable by URL, and still refused by the API if it should be.
 */
export function App() {
  const [queryClient] = useState(createQueryClient);
  return (
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        {(me) => (
          <Routes>
            <Route element={<AppLayout me={me} />}>
              <Route index element={<Home me={me} />} />

              {/* Student */}
              <Route path="profile" element={<Profile />} />
              <Route path="dashboard" element={<Dashboard />} />
              <Route path="cycles" element={<StudentCycles />} />
              <Route path="cycles/:id/jobs" element={<StudentJobs />} />
              <Route path="jobs/:id" element={<StudentJob />} />
              <Route path="applications" element={<MyApplications />} />
              <Route path="notifications" element={<MyNotifications />} />

              {/* Staff */}
              <Route path="staff/cycles" element={<StaffCycles />} />
              <Route path="staff/cycles/:id" element={<StaffCycle />} />
              <Route path="staff/cycles/:id/approvals" element={<Approvals />} />
              <Route path="staff/cycles/:id/jobs" element={<CycleJobs />} />
              <Route
                path="staff/cycles/:id/analytics"
                element={<Deferred><CycleAnalytics /></Deferred>}
              />
              <Route path="staff/jobs/:id" element={<JobBuilder />} />
              <Route path="staff/jobs/:id/board" element={<JobBoard />} />
              <Route path="staff/jobs/:id/offers" element={<Offers />} />
              <Route
                path="staff/jobs/:id/analytics"
                element={<Deferred><JobAnalytics /></Deferred>}
              />
              <Route path="staff/external" element={<ExternalOffers />} />
              <Route path="staff/cycles/:id/external" element={<CycleExternal />} />
              <Route path="staff/companies" element={<Companies />} />
              <Route path="staff/companies/:id" element={<Company />} />
              <Route path="staff/student/:enrollmentId" element={<StudentRecord />} />

              {/* Admin */}
              <Route path="admin/discipline" element={<Discipline />} />
              <Route path="admin/taxonomies" element={<Taxonomies />} />
              <Route path="admin/settings" element={<Settings />} />
              <Route path="admin/templates" element={<Templates />} />
              <Route path="admin/overrides" element={<Overrides />} />
              <Route path="admin/findings" element={<Findings />} />
              <Route path="admin/users" element={<Users />} />
              <Route
                path="admin/analytics"
                element={<Deferred><PortalAnalytics /></Deferred>}
              />
              <Route path="admin/bulk-upsert" element={<BulkUpsert />} />

              <Route path="*" element={<Navigate to="/" replace />} />
            </Route>
          </Routes>
        )}
      </AuthGate>
    </QueryClientProvider>
  );
}

/** Skeleton while a lazily-loaded screen arrives. */
function Deferred({ children }: { children: React.ReactNode }) {
  return (
    <Suspense
      fallback={
        <div className="flex flex-col gap-gap-lg">
          <Skeleton className="h-9 w-72" />
          <Skeleton className="h-64 w-full" />
        </div>
      }
    >
      {children}
    </Suspense>
  );
}
