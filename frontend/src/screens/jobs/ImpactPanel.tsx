import { useEffect } from "react";

import { usePreview } from "@/api/useScreen";
import type { BuilderPayload } from "@/api/payloads";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorState, Skeleton } from "@/components/ui/states";
import { cn } from "@/lib/cn";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import type { Rule } from "./RuleEditor";

type Impact = BuilderPayload["eligibility"]["impact"];

/** A rule is evaluated against every member, so it waits longer than a search. */
const RULE_DEBOUNCE_MS = 400;

/**
 * Who this rule admits, evaluated against the cycle's live membership.
 *
 * While the editor is untouched the panel shows the screen's own impact. Once
 * the rule is edited it dry-runs `update_job_eligibility` and shows *that*
 * result instead, so the number on screen always belongs to the rule in the
 * editor rather than to the one still in the database. The server does the
 * evaluating in both cases — a client that computed eligibility itself would
 * be a second implementation of the rule engine, and the two would diverge.
 */
export function ImpactPanel({
  cycleId,
  jobId,
  rule,
  saved,
  impact,
}: {
  cycleId: string;
  jobId: string;
  rule: Rule | null;
  saved: Rule | null;
  impact: Impact;
}) {
  const preview = usePreview("update_job_eligibility");
  const edited = JSON.stringify(rule) !== JSON.stringify(saved);
  const previewMutate = preview.mutate;
  // The raw-JSON textarea and the numeric clause inputs emit a new rule on
  // every keystroke, and each one of those is a full command execution against
  // the cycle's whole membership. Wait for the typing to stop.
  const settled = useDebouncedValue(JSON.stringify(rule), RULE_DEBOUNCE_MS);

  useEffect(() => {
    if (!edited) return;
    previewMutate({
      input: {
        cycle_id: cycleId,
        job_id: jobId,
        eligibility_rule: JSON.parse(settled) as Rule | null,
      },
    });
  }, [edited, settled, cycleId, jobId, previewMutate]);

  // The dry run returns the same three fields the screen carries for the saved
  // rule, so both paths render through one shape.
  const dry = preview.data?.summary as
    | {
        eligible_count: number;
        member_count: number;
        members: Impact["members"];
        eligibility_summary: string;
      }
    | undefined;
  const live: Impact | undefined = edited
    ? dry && {
        eligible_count: dry.eligible_count,
        member_count: dry.member_count,
        members: dry.members,
      }
    : impact;
  const summary = edited ? dry?.eligibility_summary : undefined;

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle>Who qualifies</CardTitle>
        {edited ? (
          <span className="text-body-sm text-warning">Unsaved rule</span>
        ) : null}
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {edited && preview.isPending ? (
          <>
            <Skeleton className="h-8 w-32" />
            <Skeleton className="h-40 w-full" />
          </>
        ) : edited && preview.isError ? (
          <ErrorState error={preview.error} title="This rule was rejected" />
        ) : live ? (
          <>
            {summary ? (
              <p className="rounded border border-border bg-muted p-gap-lg text-body-md text-foreground">
                {summary}
              </p>
            ) : null}

            <p className="text-body-md text-foreground">
              <span className="tabular text-headline-lg font-semibold">
                {live.eligible_count}
              </span>
              <span className="text-muted-foreground">
                {" "}
                of {live.member_count} active member
                {live.member_count === 1 ? "" : "s"} qualify
              </span>
            </p>

            {live.member_count === 0 ? (
              <p className="text-body-sm text-muted-foreground">
                Nobody has joined this cycle yet, so there is nothing to evaluate the rule
                against.
              </p>
            ) : live.members.length === 0 ? (
              <p className="text-body-sm text-muted-foreground">
                No member-level results were returned for this evaluation.
              </p>
            ) : (
              <ul className="flex flex-col gap-gap-md">
                {live.members.map((member) => (
                  <li
                    key={member.enrollment_id}
                    className={cn(
                      "rounded border p-gap-lg",
                      member.eligible
                        ? "border-success-border bg-success-subtle"
                        : "border-border bg-card",
                    )}
                  >
                    <div className="flex items-baseline justify-between gap-gap-md">
                      <span className="text-body-md font-medium text-foreground">
                        {member.full_name}
                      </span>
                      {member.roll_number ? (
                        <span className="tabular text-body-sm text-muted-foreground">
                          {member.roll_number}
                        </span>
                      ) : null}
                    </div>
                    {member.eligible ? (
                      <p className="mt-gap-tight text-body-sm text-success">Qualifies</p>
                    ) : member.reasons.length === 0 ? (
                      <p className="mt-gap-tight text-body-sm text-muted-foreground">
                        Does not qualify; no additional reason was supplied.
                      </p>
                    ) : (
                      <ul className="mt-gap-md flex flex-col gap-gap-tight">
                        {member.reasons.map((reason, index) => (
                          <li key={index} className="text-body-sm text-muted-foreground">
                            {reason.human}
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </>
        ) : null}
      </CardBody>
    </Card>
  );
}
