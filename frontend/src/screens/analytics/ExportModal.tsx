import { ArrowDown, ArrowUp, Download, Save } from "lucide-react";
import { useEffect, useState } from "react";

import type { ExportColumnOption } from "@/api/payloads";
import { ApiError, toApiError } from "@/api/problem";
import { useCommand } from "@/api/useScreen";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Field } from "@/components/ui/field";
import { Select } from "@/components/ui/input";
import { ErrorState } from "@/components/ui/states";

/**
 * ANA-4's column picker and the two delivery paths behind it.
 *
 * The columns offered here come from the screen that opened the modal, which
 * got them from the server's registry — the same registry `request_export`
 * validates against. That is the the design review 4.22 shape: the control offers
 * exactly what the command accepts, rather than a list maintained beside it.
 *
 * Both delivery paths are visible to the user as one action. A small export
 * comes back `ready` and downloads immediately; a large one comes back
 * `queued` and this polls until the worker finishes, saying so meanwhile,
 * because a button that appears to do nothing for two minutes is a button
 * people press four times.
 */

const POLL_MS = 2000;

interface ExportResult {
  export_id: string;
  status: string;
  mode: string;
  row_count: number;
}

export function ExportButton({
  cycleId,
  jobId,
  kind,
  columns,
  label = "Export",
  cohorts,
  preset,
}: {
  cycleId: string;
  jobId?: string;
  kind: "job_applications" | "cycle_memberships";
  columns?: ExportColumnOption[];
  label?: string;
  cohorts?: { value: string; label: string; roundId?: string }[];
  preset?: string[] | null;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary">
          <Download aria-hidden className="h-3.5 w-3.5" /> {label}
        </Button>
      </DialogTrigger>
      {open ? (
        <ExportDialog
          cycleId={cycleId}
          jobId={jobId}
          kind={kind}
          columns={columns ?? []}
          cohorts={cohorts}
          preset={preset}
        />
      ) : null}
    </Dialog>
  );
}

function ExportDialog({
  cycleId,
  jobId,
  kind,
  columns,
  cohorts,
  preset,
}: {
  cycleId: string;
  jobId?: string;
  kind: "job_applications" | "cycle_memberships";
  columns: ExportColumnOption[];
  cohorts?: { value: string; label: string; roundId?: string }[];
  preset?: string[] | null;
}) {
  const request = useCommand("request_export");
  const [format, setFormat] = useState<"xlsx" | "csv">("xlsx");
  const [chosen, setChosen] = useState<string[]>(() =>
    preset ?? columns.filter((column) => DEFAULTS.has(column.key)).map((column) => column.key),
  );
  const [cohort, setCohort] = useState(cohorts?.[0]?.value ?? "applicants");
  const [passedOnly, setPassedOnly] = useState(true);
  const savePreset = useCommand("save_export_preset");
  const [result, setResult] = useState<ExportResult | null>(null);
  const [ready, setReady] = useState<string | null>(null);
  const [pollError, setPollError] = useState<unknown>(null);

  // The >5k path: poll the status route until the worker flips it to ready.
  useEffect(() => {
    if (result === null || result.status !== "queued") return;
    let cancelled = false;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`/api/v1/exports/${result.export_id}`, {
          credentials: "same-origin",
        });
        if (!response.ok) {
          setPollError(await toApiError(response));
          setResult({ ...result, status: "failed" });
          return;
        }
        const body: { status: string; download_url: string | null; error: string | null } =
          await response.json();
        if (cancelled) return;
        if (body.status === "ready" && body.download_url) {
          setReady(body.download_url);
          setResult({ ...result, status: "ready" });
        } else if (body.status === "failed") {
          setPollError(new ApiError({
            type: "about:blank",
            title: "Export failed",
            status: 500,
            detail: "The export could not be built.",
          }));
          setResult({ ...result, status: "failed" });
        }
      } catch {
        // A dropped poll is not a failed export; the next tick tries again.
      }
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [result]);

  const submit = async () => {
    setPollError(null);
    const response = await request.mutateAsync({
      input: {
        cycle_id: cycleId,
        ...(jobId ? { job_id: jobId } : {}),
        kind,
        format,
        columns: chosen,
        cohort: cohort === "offers" ? "offers" : cohort === "applicants" ? "applicants" : "round",
        passed_only: passedOnly,
        ...(cohorts?.find((item) => item.value === cohort)?.roundId
          ? { round_id: cohorts.find((item) => item.value === cohort)!.roundId }
          : {}),
      },
    });
    const built = response.summary as unknown as ExportResult;
    setResult(built);
    if (built.status === "ready") {
      setReady(`/api/v1/exports/${built.export_id}/download`);
    }
  };

  const grouped = groupByFamily(columns);
  const move = (key: string, delta: number) => setChosen((current) => {
    const from = current.indexOf(key);
    const to = from + delta;
    if (from < 0 || to < 0 || to >= current.length) return current;
    const next = [...current];
    const moved = next[from];
    const displaced = next[to];
    if (moved === undefined || displaced === undefined) return current;
    next[from] = displaced;
    next[to] = moved;
    return next;
  });

  return (
    <DialogContent className="max-w-2xl">
      <DialogHeader>
        <DialogTitle>Export</DialogTitle>
        <DialogDescription>
          Every export is recorded — who asked, which columns, and which filters.
        </DialogDescription>
      </DialogHeader>
      <div className="p-container-padding">

        {cohorts?.length ? (
          <Field label="Students">
            {(field) => (
              <Select {...field} value={cohort} onChange={(event) => setCohort(event.target.value)}>
                {cohorts.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </Select>
            )}
          </Field>
        ) : null}

        {cohorts?.find((item) => item.value === cohort)?.roundId ? (
          <label className="mt-gap-md flex items-center gap-gap-tight text-body-sm">
            <Checkbox
              checked={passedOnly}
              onChange={(event) => setPassedOnly(event.target.checked)}
            />
            Export only students who passed this round
          </label>
        ) : null}

        {columns.length > 0 ? (
          <div className="mt-gap-md flex flex-col gap-gap-md">
            {Object.entries(grouped).map(([family, entries]) => (
              <fieldset key={family}>
                <legend className="text-body-sm font-medium capitalize">{family}</legend>
                <div className="mt-1 grid grid-cols-2 gap-1 sm:grid-cols-3">
                  {entries.map((column) => (
                    <label
                      key={column.key}
                      className="flex items-center gap-gap-tight text-body-sm"
                    >
                      <Checkbox
                        aria-label={column.label}
                        checked={chosen.includes(column.key)}
                        onChange={(event) =>
                          setChosen((current) =>
                            event.target.checked
                              ? [...current, column.key]
                              : current.filter((key) => key !== column.key),
                          )
                        }
                      />
                      {column.label}
                    </label>
                  ))}
                </div>
              </fieldset>
            ))}
          </div>
        ) : (
          <p className="mt-gap-md text-body-sm text-muted-foreground">
            The default columns will be used.
          </p>
        )}

        {columns.length > 0 ? (
          <div className="mt-gap-md rounded border border-border p-gap-md">
            <div className="mb-gap-md flex items-center justify-between">
              <p className="text-body-sm font-medium">Selected column order</p>
              {jobId ? (
                <Button variant="secondary" disabled={!chosen.length || savePreset.isPending}
                  onClick={() => void savePreset.mutateAsync({ input: { cycle_id: cycleId, job_id: jobId, columns: chosen } })}>
                  <Save aria-hidden className="h-3.5 w-3.5" /> Save for this job
                </Button>
              ) : null}
            </div>
            <ol className="flex flex-col gap-1">
              {chosen.map((key, index) => {
                const option = columns.find((item) => item.key === key);
                return <li key={key} className="flex items-center justify-between rounded bg-muted/40 px-2 py-1 text-body-sm">
                  <span>{index + 1}. {option?.label ?? key}</span>
                  <span className="flex gap-1">
                    <Button variant="ghost" aria-label={`Move ${option?.label ?? key} up`} disabled={index === 0} onClick={() => move(key, -1)}><ArrowUp className="h-3.5 w-3.5" /></Button>
                    <Button variant="ghost" aria-label={`Move ${option?.label ?? key} down`} disabled={index === chosen.length - 1} onClick={() => move(key, 1)}><ArrowDown className="h-3.5 w-3.5" /></Button>
                  </span>
                </li>;
              })}
            </ol>
          </div>
        ) : null}

        <div className="mt-gap-md">
          <Field label="Format">
            {(field) => (
              <Select
                {...field}
                value={format}
                onChange={(event) =>
                  setFormat(event.currentTarget.value === "csv" ? "csv" : "xlsx")
                }
              >
                <option value="xlsx">Excel (.xlsx)</option>
                <option value="csv">CSV (.csv)</option>
              </Select>
            )}
          </Field>
        </div>

        {request.isError ? (
          <div className="mt-gap-md">
            <ErrorState error={request.error} title="Could not start the export" />
          </div>
        ) : null}
        {pollError ? (
          <div className="mt-gap-md">
            <ErrorState error={pollError} title="Could not build the export" />
          </div>
        ) : null}

        {result !== null && result.status === "queued" ? (
          <p className="mt-gap-md text-body-sm text-muted-foreground" role="status">
            Building {result.row_count.toLocaleString()} {result.row_count === 1 ? "row" : "rows"}. This one is large
            enough to be built in the background — this will keep checking.
          </p>
        ) : null}

        <div className="mt-gap-lg flex justify-end gap-gap-md">
          <DialogClose asChild>
            <Button variant="secondary">Close</Button>
          </DialogClose>
          {ready ? (
            <Button asChild variant="primary">
              <a href={ready} download>
                Download
              </a>
            </Button>
          ) : (
            <Button
              variant="primary"
              onClick={() => void submit()}
              disabled={request.isPending || result?.status === "queued"}
            >
              {request.isPending ? "Requesting…" : "Build export"}
            </Button>
          )}
        </div>
      </div>
    </DialogContent>
  );
}

/** Mirrors the server's `default_columns`: identity and status, nothing more. */
const DEFAULTS = new Set([
  "full_name",
  "roll_number",
  "institute_email",
  "status",
  "membership_status",
  "resume_link",
]);

function groupByFamily(columns: ExportColumnOption[]) {
  const grouped: Record<string, ExportColumnOption[]> = {};
  for (const column of columns) {
    (grouped[column.family] ??= []).push(column);
  }
  return grouped;
}
