import { Link } from "react-router-dom";

import type { AcademicStandingPayload } from "@/api/payloads";
import { Button } from "@/components/ui/button";

/** Collection notice, not a membership revocation or application gate. */
export function AcademicStandingNotice({
  standing,
  onProfile = false,
}: {
  standing: AcademicStandingPayload | undefined;
  onProfile?: boolean;
}) {
  if (!standing || standing.status === "current" || standing.status === "unconfigured") return null;
  return (
    <section
      aria-label="Academic details needed"
      className="rounded border border-border bg-muted p-gap-lg"
    >
      <h2 className="text-body-md font-semibold text-foreground">
        {standing.status === "stale" ? "Confirm your year of study" : "Complete your academic details"}
      </h2>
      <p className="mt-gap-md text-body-sm text-muted-foreground">
        Record your current year of study (1–8) for {standing.current_session_label}.
        {standing.status === "stale" ? " Your previous academic-session record is out of date." : ""}
        {standing.collection_only ? " Your existing memberships, applications and offers are unchanged. This collection phase does not block applications." : ""}
      </p>
      {!onProfile ? (
        <Button variant="link" asChild>
          <Link to="/profile#academic-standing">Complete academic details</Link>
        </Button>
      ) : null}
    </section>
  );
}
