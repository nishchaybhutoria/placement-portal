import type { ActionPermission } from "@/api/payloads";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { humanise } from "@/lib/text";

/**
 * Taking a member out of a cycle, and putting them back (Behavior CYC-3.7, 3.8).
 *
 * "Remove this person from the cycle" is a week-one request over a real season,
 * and until this control existed the two commands that do it had no browser
 * surface at all — `restore_membership` was even a repair the consistency
 * checker names and no human could press.
 *
 * Removal cascades: CYC-4 auto-withdraws that cycle's in-flight applications.
 * So the preview names each application it will close and each one it cannot,
 * per row and never as a count (the design review §4.21, widened by §4.37) — a
 * coordinator removing someone mid-process has to see the three applications
 * that closes before they press it.
 *
 * The refused case renders a disabled control with the server's own sentence
 * rather than nothing: a `pending` membership cannot be removed, and a button
 * that quietly vanishes teaches nobody why.
 */

interface CascadeRow {
  application_id?: string;
  full_name?: string | null;
  job?: string | null;
  from_status?: string | null;
  status?: string | null;
}

interface ExitSummary {
  auto_withdrawn?: CascadeRow[];
  untouched?: CascadeRow[];
}

export function MembershipExit({
  cycleId,
  membershipId,
  fullName,
  status,
  actions,
}: {
  cycleId: string;
  membershipId: string;
  fullName: string;
  status: string;
  actions: {
    remove_membership?: ActionPermission;
    restore_membership?: ActionPermission;
  };
}) {
  // One membership is in exactly one of the two situations: an active member
  // can be removed, a withdrawn or removed one restored. The transition table
  // decides that, and the server has already read it.
  const removable = actions.remove_membership;
  const restorable = actions.restore_membership;
  const offering =
    restorable?.allowed === true
      ? "restore"
      : removable?.allowed === true
        ? "remove"
        : status === "withdrawn" || status === "removed"
          ? "restore"
          : "remove";
  const permission = offering === "restore" ? restorable : removable;
  if (!permission) return null;

  if (!permission.allowed) {
    return (
      <Button variant="ghost" size="sm" disabled title={permission.human ?? undefined}>
        {offering === "restore" ? "Restore" : "Remove"}
      </Button>
    );
  }

  if (offering === "restore") {
    return (
      <PreviewConfirm
        command="restore_membership"
        input={{ cycle_id: cycleId, membership_id: membershipId }}
        title={`Restore ${fullName} to this cycle?`}
        // Restoration of the applications is deliberately separate (INT-1):
        // saying so here stops a coordinator assuming this undoes the cascade.
        description="They become an active member again and can apply. Applications closed when they left stay closed — reinstate those one at a time from the student's record."
        confirmLabel="Restore membership"
        renderSummary={renderCascade}
        trigger={
          <Button variant="secondary" size="sm">
            Restore
          </Button>
        }
      />
    );
  }

  return (
    <PreviewConfirm
      command="remove_membership"
      input={{ cycle_id: cycleId, membership_id: membershipId, reason: "" }}
      title={`Remove ${fullName} from this cycle?`}
      description="This closes their in-flight applications in this cycle. The preview names every one."
      confirmLabel="Remove member"
      destructive
      choices={[
        {
          name: "reason",
          label: "Reason",
          kind: "textarea",
          required: true,
          hint: "Shown to the student, and kept on the audit trail.",
        },
      ]}
      renderSummary={renderCascade}
      trigger={
        <Button variant="destructive-ghost" size="sm">
          Remove
        </Button>
      }
    />
  );
}

function renderCascade(summary: unknown) {
  const { auto_withdrawn: withdrawn = [], untouched = [] } = (summary ??
    {}) as ExitSummary;
  return (
    <div className="flex flex-col gap-gap-lg">
      <section>
        <p className="text-label-caps uppercase text-muted-foreground">
          Applications this closes ({withdrawn.length})
        </p>
        {withdrawn.length === 0 ? (
          <p className="mt-gap-tight text-body-sm text-muted-foreground">
            None — they have nothing in flight in this cycle.
          </p>
        ) : (
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {withdrawn.map((row) => (
              <li key={row.application_id} className="text-body-md text-foreground">
                {row.job ?? "Unnamed job"}
                <span className="text-muted-foreground">
                  {" → auto-withdrawn"}
                  {row.from_status ? ` (was ${humanise(row.from_status).toLowerCase()})` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      {untouched.length > 0 ? (
        <section>
          <p className="text-label-caps uppercase text-warning">
            Left open ({untouched.length})
          </p>
          {/* APP-4.13 moves in_progress and pending_offer only. An offered or
              accepted application carries an offer, and only terminate_offer
              may unwind one — so these are named, not silently left behind. */}
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {untouched.map((row) => (
              <li key={row.application_id} className="text-body-sm text-foreground">
                {row.job ?? "Unnamed job"}
                <span className="text-muted-foreground">
                  {row.status ? ` — ${humanise(row.status).toLowerCase()}` : ""}
                  {"; it carries an offer, so terminate that first"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}
