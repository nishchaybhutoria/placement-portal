import type { SubjectOverride } from "@/api/payloads";
import { StatusChip } from "@/components/ui/statusChip";
import { formatDate } from "@/lib/date";
import { humanise } from "@/lib/text";

/** Resolver-classified overrides relevant to the subject beside this panel. */
export function SubjectOverrides({
  overrides,
  empty = false,
}: {
  overrides: readonly SubjectOverride[] | undefined;
  /** Compact application cards omit an empty panel; top-level pages do not. */
  empty?: boolean;
}) {
  const rows = overrides ?? [];
  if (rows.length === 0 && !empty) return null;
  return (
    <div>
      <h3 className="text-label-caps uppercase text-muted-foreground">
        Overrides in force
      </h3>
      {rows.length === 0 ? (
        <p className="mt-gap-tight text-body-sm text-muted-foreground">
          No active or expired overrides are relevant to this subject.
        </p>
      ) : (
        <ul className="mt-gap-md grid gap-gap-md sm:grid-cols-2">
          {rows.map((row) => (
            <li key={row.id} className="rounded border border-border p-gap-md">
              <div className="flex flex-wrap items-center justify-between gap-gap-tight">
                <p className="font-medium text-foreground">
                  {humanise(row.rule_domain)}
                </p>
                <StatusChip domain="override" value={row.state} />
              </div>
              <p className="mt-gap-tight text-body-sm text-muted-foreground">
                {row.allow ? "Allows past the gate" : "Blocks at the gate"} · {humanise(row.scope)}
                {row.subject_label ? ` · ${row.subject_label}` : ""}
              </p>
              <p className="mt-gap-tight text-body-sm text-foreground">{row.reason}</p>
              {row.expires_at ? (
                <p className="mt-gap-tight text-body-sm text-muted-foreground">
                  {row.state === "expired" ? "Expired " : "Expires "}
                  {formatDate(row.expires_at)}
                </p>
              ) : null}
              {row.state === "shadowed" ? (
                <p className="mt-gap-tight text-body-sm text-muted-foreground">
                  A more specific, blocking, or newer override currently wins.
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
