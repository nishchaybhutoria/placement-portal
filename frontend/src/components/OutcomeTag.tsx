import type { ActionPermission } from "@/api/payloads";
import { PreviewConfirm } from "./PreviewConfirm";
import { humanise } from "@/lib/text";
import { Button } from "./ui/button";

/** ANA-3's three compliance outcomes, as `outcome_tag_t` declares them. */
const OUTCOME_TAGS = [
  { value: "higher_studies", label: "Higher studies" },
  { value: "entrepreneurship", label: "Entrepreneurship" },
  { value: "not_seeking", label: "Not seeking" },
] as const;

/**
 * The ANA-3 outcome tag on one cycle membership.
 *
 * The tag is what separates "unplaced" from "not looking for a placement", and
 * ANA-3's seeking-adjusted rate divides by exactly that difference — so the
 * control belongs on the membership row, where staff already know the answer
 * because they have just heard it from the student. Both screens that render
 * such a row use this one control, and both read the server's permission
 * rather than deciding for themselves: a coordinator tags inside the cycles
 * they run, an archived season tags nothing at all.
 */
export function OutcomeTag({
  cycleId,
  membershipId,
  subject,
  current,
  permission,
}: {
  cycleId: string;
  membershipId: string;
  /** Whose outcome this is, for the dialog's title. */
  subject: string;
  current: string | null;
  permission: ActionPermission;
}) {
  const label = current ? humanise(current) : "Not tagged";
  if (!permission.allowed) {
    return (
      <span
        className="text-body-sm text-muted-foreground"
        title={permission.human ?? undefined}
      >
        {label}
      </span>
    );
  }
  return (
    <PreviewConfirm
      command="set_outcome_tag"
      input={{ cycle_id: cycleId, membership_id: membershipId, outcome_tag: null }}
      title={`Tag ${subject}?`}
      description="Compliance reporting divides by this: a student who is not seeking a placement is not an unplaced one."
      confirmLabel="Save tag"
      choices={[
        {
          name: "outcome_tag",
          label: "Outcome",
          kind: "select",
          initialValue: current ?? "",
          options: OUTCOME_TAGS,
          hint: "Leave unselected to clear the tag.",
        },
      ]}
      transformInput={(input) => ({
        ...input,
        // An unselected choice means "no tag", which the command spells null.
        outcome_tag: (input.outcome_tag || null) as typeof input.outcome_tag,
      })}
      trigger={
        <Button variant="ghost" size="sm">
          {label}
        </Button>
      }
    />
  );
}
