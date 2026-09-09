import type { CommandInput } from "@/api/client";
import type { ActionPermission } from "@/api/payloads";
import { PreviewConfirm, type Choice } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { humanise } from "@/lib/text";

/**
 * One INT-2 grant form, wherever the record it is about happens to live.
 *
 * An override's *scope* is the whole point of it — "let this student apply
 * late" and "let everyone in this cycle apply late" are different decisions —
 * and the only grant form the product had was cycle-wide, on the register.
 * Every other scope existed in `create_override` and was reachable by nothing.
 *
 * So the form goes where the subject is: the cycle on the register, the student
 * on their record, the job in its builder. Each passes the one scope column it
 * knows (plus `cycle_id` where the command requires it on the wire), and they
 * share these choices so a grant means the same thing from all three.
 */

/** An exception that must be remembered to be revoked is one that will not be. */
export const EXPIRY_CHOICE: Choice = {
  name: "expires_at",
  label: "Expires (optional)",
  kind: "datetime",
  hint: "After this instant the override is inert; leave blank for a standing one.",
};

export function overrideChoices(domains: readonly string[]): Choice[] {
  return [
    {
      name: "rule_domain",
      label: "Rule domain",
      kind: "select",
      required: true,
      options: domains.map((domain) => ({ value: domain, label: humanise(domain) })),
      hint: "Membership, job-open, duplicate-application and penalty gates are not overridable.",
    },
    {
      name: "allow",
      label: "Decision",
      kind: "select",
      required: true,
      coerce: "boolean",
      options: [
        { value: "true", label: "Allow past this gate" },
        { value: "false", label: "Block at this gate" },
      ],
      hint: "At equal specificity, a block beats an allow.",
    },
    {
      name: "reason",
      label: "Reason",
      kind: "textarea",
      required: true,
      hint: "Stored on the override and shown in the register.",
    },
    EXPIRY_CHOICE,
  ];
}

export function GrantOverride({
  scope,
  title,
  description,
  domains,
  label = "Grant an override",
  disabled = false,
  permission,
}: {
  /** The one scope column this grant names, plus `cycle_id` where required. */
  scope:
    | { cycle_id: string }
    | { enrollment_id: string }
    | { cycle_id: string; job_id: string }
    | { cycle_id: string; application_id: string };
  title: string;
  description: string;
  domains: readonly string[];
  label?: string;
  disabled?: boolean;
  permission?: ActionPermission;
}) {
  // The server owns scope/domain legality. The empty fallback only keeps a
  // stale fixture from crashing; it disables the trigger and cannot be posted.
  const availableDomains = domains ?? [];
  const initialDomain = (availableDomains[0] ??
    "") as CommandInput<"create_override">["rule_domain"];
  const unavailable = disabled || permission?.allowed === false || availableDomains.length === 0;
  return (
    <PreviewConfirm
      command="create_override"
      input={{
        ...scope,
        rule_domain: initialDomain,
        allow: true,
        reason: "",
      }}
      title={title}
      description={description}
      confirmLabel="Grant"
      choices={overrideChoices(availableDomains)}
      trigger={
        <Button
          variant="secondary"
          disabled={unavailable}
          title={permission?.human ?? undefined}
        >
          {label}
        </Button>
      }
    />
  );
}
