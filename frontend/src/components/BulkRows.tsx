import type { ReactNode } from "react";

import { reasonText } from "@/lib/reasons";

/**
 * The per-row plan of any bulk command, before anything is committed.
 *
 * the design review §4.21 asks two things of a bulk preview, and §4.37 makes them bind
 * every one of them rather than the M10 flow they were written for: unmatched
 * identifiers are **listed individually, never counted** — fifty pasted rolls
 * with three typos is a request to be shown the three — and the preview states
 * the **per-row planned effect**, not an aggregate. An identifier swallowed
 * into a count is a student who never gets approved, advanced or offered, and
 * nobody finds out until they complain.
 *
 * Every bulk command already returns the same triple per row: what produced
 * the row, whether it will apply, and why not if it will not. So one component
 * renders all of them, and a command with a richer row adds to it through
 * `describe` rather than growing a renderer of its own that reports a skip
 * differently from its neighbour.
 *
 * The fourth bucket is the point of the shape: a row whose status is neither
 * applied nor skipped — a stale view, an external offer that vanished between
 * render and confirm — lands in *Cannot be done* rather than in nothing at
 * all, which is what the board's own renderer used to do with it.
 */
export interface BulkRow {
  /** What the caller sent: a pasted roll or email, or an id it ticked. */
  identifier?: string | null;
  application_id?: string | null;
  membership_id?: string | null;
  external_offer_id?: string | null;
  full_name?: string | null;
  roll_number?: string | null;
  /** `ok` / `applied` will happen; `skipped` and `error` carry a reason. */
  status: string;
  reason?: string | null;
  /** The sentence the decider already produced, not the bare code. */
  human?: string | null;
  to_status?: string | null;
  to_round?: string | null;
}

const UNMATCHED = "unmatched_identifier";
const APPLYING = new Set(["ok", "applied"]);
/**
 * A row that was matched and is already where it is being asked to go.
 *
 * `assign_venue_timing` reports it for a student whose venue and time the
 * sheet does not move (the design review §4.46) — re-uploading a corrected sheet is
 * the ordinary case, not a failure, and it must not read as one.
 */
const UNCHANGED = "unchanged";

export interface BulkRowsProps<Row extends BulkRow> {
  summary: { rows?: Row[] };
  /** Heading for the rows that will apply — "Will move", "Will approve". */
  applyLabel: string;
  /** The planned effect of one applying row, appended after its name. */
  describe?: (row: Row) => ReactNode;
  /**
   * A name for a row that carries only an id.
   *
   * `cancel_job` and `attach_external_offers` report an id because that is
   * what they were sent; the screen that sent it knows the person, and a
   * preview naming UUIDs answers nobody's question.
   */
  resolveName?: (row: Row) => string | null | undefined;
}

export function BulkRows<Row extends BulkRow>({
  summary,
  applyLabel,
  describe,
  resolveName,
}: BulkRowsProps<Row>) {
  const rows = summary.rows ?? [];
  const unmatched = rows.filter((row) => row.reason === UNMATCHED);
  const rest = rows.filter((row) => row.reason !== UNMATCHED);
  const applying = rest.filter((row) => APPLYING.has(row.status));
  const skipped = rest.filter((row) => row.status === "skipped");
  const unchanged = rest.filter((row) => row.status === UNCHANGED);
  // Whatever is left is neither applied, deliberately skipped, nor already
  // right. Showing it under its own heading is how a row can never go missing
  // from a preview just because a command grew a status this component has not
  // heard of.
  const failed = rest.filter(
    (row) =>
      !APPLYING.has(row.status) &&
      row.status !== "skipped" &&
      row.status !== UNCHANGED,
  );

  return (
    <div className="flex flex-col gap-gap-lg">
      <section>
        <p className="text-label-caps uppercase text-muted-foreground">
          {applyLabel} ({applying.length})
        </p>
        {applying.length === 0 ? (
          <p className="mt-gap-tight text-body-sm text-muted-foreground">Nobody.</p>
        ) : (
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {applying.map((row, index) => (
              <li key={rowKey(row, index)} className="text-body-md text-foreground">
                {name(row, resolveName)}
                {describe ? <span className="text-muted-foreground">{describe(row)}</span> : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      {unmatched.length > 0 ? (
        <section>
          <p className="text-label-caps uppercase text-danger">
            Matched nothing ({unmatched.length})
          </p>
          {/* Named, never counted: these are the ones to go and check. */}
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {unmatched.map((row, index) => (
              <li key={rowKey(row, index)} className="text-body-md text-foreground">
                {row.identifier ?? name(row, resolveName)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {skipped.length > 0 ? (
        <section>
          <p className="text-label-caps uppercase text-muted-foreground">
            Skipped ({skipped.length})
          </p>
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {skipped.map((row, index) => (
              <li key={rowKey(row, index)} className="text-body-sm text-muted-foreground">
                {name(row, resolveName)} —{" "}
                {/* The server said *which* cause it hit; a de-underscored code
                    would flatten "Not sitting in a round" back to a shrug. */}
                {reasonText(row.reason ?? "", row.human ?? undefined)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {unchanged.length > 0 ? (
        <section>
          <p className="text-label-caps uppercase text-muted-foreground">
            Already up to date ({unchanged.length})
          </p>
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {unchanged.map((row, index) => (
              <li key={rowKey(row, index)} className="text-body-sm text-muted-foreground">
                {name(row, resolveName)} — nothing changes; they will not be emailed again
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      {failed.length > 0 ? (
        <section>
          <p className="text-label-caps uppercase text-danger">
            Cannot be done ({failed.length})
          </p>
          <ul className="mt-gap-tight flex flex-col gap-gap-tight">
            {failed.map((row, index) => (
              <li key={rowKey(row, index)} className="text-body-sm text-foreground">
                {name(row, resolveName)} —{" "}
                {reasonText(row.reason ?? "", row.human ?? undefined)}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  );
}

function name<Row extends BulkRow>(
  row: Row,
  resolveName?: (row: Row) => string | null | undefined,
): string {
  const resolved = resolveName?.(row);
  if (row.full_name) {
    return row.roll_number ? `${row.full_name} (${row.roll_number})` : row.full_name;
  }
  if (resolved) return resolved;
  return (
    row.identifier ||
    row.application_id ||
    row.membership_id ||
    row.external_offer_id ||
    "Unnamed row"
  );
}

function rowKey(row: BulkRow, index: number): string {
  return `${row.identifier ?? row.application_id ?? row.membership_id ?? row.external_offer_id ?? index}:${index}`;
}
