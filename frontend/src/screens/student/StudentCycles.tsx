import { Link } from "react-router-dom";

import { payload, type StudentCyclesPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { StudentCycleSections } from "@/components/StudentCycleSections";
import { ErrorState, ScreenSkeleton } from "@/components/ui/states";

/** The cycles a student is in or could join (LLD §11.3 `cycles/joinable`). */
export function StudentCycles() {
  const screen = useScreen("cycles/joinable");

  if (screen.isPending) return <ScreenSkeleton variant="cards" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<StudentCyclesPayload>(screen.data);

  return (
    <>
      <PageHeader
        title="Cycles"
        subtitle="Recruitment cycles you are in, and those you could join."
      />

      {!data.profile_complete ? (
        <div className="rounded border border-warning-border bg-warning-subtle p-container-padding">
          <p className="text-body-md font-semibold text-warning">
            Your profile is not complete
          </p>
          <p className="mt-gap-tight text-body-md text-foreground">
            Joining a cycle needs every field on the checklist, and a resume. Finish it on{" "}
            <Link to="/profile" className="text-accent hover:underline">
              your profile
            </Link>
            .
          </p>
        </div>
      ) : null}

      <StudentCycleSections
        cycles={data.cycles}
        enrollmentId={data.enrollment_id}
        resumes={data.resumes}
      />
    </>
  );
}
