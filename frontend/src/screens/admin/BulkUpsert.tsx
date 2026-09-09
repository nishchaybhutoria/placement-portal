import { useState } from "react";

import { uploadProfileRows, type ProfileUpload } from "@/api/client";
import { payload, type AdminBulkUpsertPayload } from "@/api/payloads";
import { useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { newIdempotencyKey } from "@/lib/idempotency";

export function BulkUpsert() {
  const screen = useScreen("admin/bulk-upsert");
  const [upload, setUpload] = useState<ProfileUpload | null>(null);
  const [parseError, setParseError] = useState<unknown>(null);
  const [parsing, setParsing] = useState(false);
  const [batchKey, setBatchKey] = useState("");
  const [report, setReport] = useState<unknown>(null);

  if (screen.isPending) return <ScreenSkeleton variant="form" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }
  const data = payload<AdminBulkUpsertPayload>(screen.data);

  async function parse(file: File | undefined) {
    if (!file) return;
    setParsing(true);
    setParseError(null);
    setReport(null);
    try {
      setUpload(await uploadProfileRows(file));
      setBatchKey(newIdempotencyKey());
    } catch (error) {
      setUpload(null);
      setParseError(error);
    } finally {
      setParsing(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Bulk profile upsert"
        subtitle="Parse a semester sheet, inspect every row's plan, then commit that exact batch."
      />
      <Card>
        <CardHeader><CardTitle>Upload</CardTitle></CardHeader>
        <CardBody className="flex flex-col gap-gap-lg">
          <Field label="CSV or XLSX" hint={`Match on ${data.email_column}; accepted admin columns: ${data.columns.map((column) => column.key).join(", ")}.`}>
            {(field) => (
              <Input
                {...field}
                type="file"
                accept=".csv,.xlsx"
                disabled={parsing}
                onChange={(event) => void parse(event.target.files?.[0])}
              />
            )}
          </Field>
          {parseError ? <ErrorState error={parseError} title="Could not parse upload" /> : null}
          {upload ? (
            <>
              <ParsedRows upload={upload} />
              <PreviewConfirm
                command="bulk_upsert_profiles"
                input={{ rows: upload.rows, batch_key: batchKey }}
                title={`Preview ${upload.rows.length} profile row${upload.rows.length === 1 ? "" : "s"}?`}
                description="The dry run resolves each email to its current enrollment and reports update, stage, or error before anything is written."
                confirmLabel="Commit batch"
                renderSummary={(summary) => <BulkReport summary={summary} />}
                onDone={(summary) => setReport(summary)}
                trigger={<Button disabled={upload.rows.length === 0 || upload.errors.length > 0}>Preview and commit</Button>}
              />
            </>
          ) : null}
          {report ? (
            <div className="rounded border border-success-border bg-success-subtle p-gap-lg">
              <p className="text-body-md font-semibold text-success">Commit report</p>
              <BulkReport summary={report} />
            </div>
          ) : null}
        </CardBody>
      </Card>
      <StagedRows data={data} />
    </>
  );
}

function ParsedRows({ upload }: { upload: ProfileUpload }) {
  return (
    <div className="overflow-x-auto rounded border border-border">
      {upload.rows.length === 0 ? (
        <EmptyState message="The upload contains no valid profile rows." />
      ) : (
        <table className="w-full text-left text-body-md">
          <thead className="bg-muted text-label-caps uppercase text-muted-foreground">
            <tr>
              <th className="px-table-cell-x py-table-cell-y text-right">Row</th>
              <th className="px-table-cell-x py-table-cell-y">Institute email</th>
              <th className="px-table-cell-x py-table-cell-y">Provided fields</th>
            </tr>
          </thead>
          <tbody>
            {upload.rows.map((row) => (
              <tr key={row.row_number} className="border-t border-border hover:bg-muted">
                <td className="px-table-cell-x py-table-cell-y text-right tabular">{row.row_number}</td>
                <td className="px-table-cell-x py-table-cell-y">{row.institute_email}</td>
                <td className="px-table-cell-x py-table-cell-y">{Object.keys(row.fields).join(", ") || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {upload.errors.length > 0 ? (
        <ul className="border-t border-danger-border bg-danger-subtle p-gap-lg text-body-sm text-danger">
          {upload.errors.map((error, index) => <li key={index}>{error.row_number ? `Row ${error.row_number}: ` : ""}{error.human}</li>)}
        </ul>
      ) : null}
    </div>
  );
}

function BulkReport({ summary }: { summary: unknown }) {
  const rows = (summary as {
    rows?: {
      row_number?: number;
      institute_email?: string;
      result?: string;
      reasons?: { human?: string; code?: string }[];
    }[];
  }).rows ?? [];
  if (rows.length === 0) return <p className="text-body-sm text-muted-foreground">No rows.</p>;
  return (
    <ul className="mt-gap-md flex flex-col gap-gap-tight text-body-sm">
      {rows.map((row, index) => {
        const reasons = row.reasons
          ?.map((reason) => reason.human ?? reason.code)
          .filter((reason): reason is string => Boolean(reason))
          .join("; ");
        return (
          <li key={`${row.row_number ?? index}-${row.institute_email ?? ""}`} className="text-foreground">
            {row.row_number ? `Row ${row.row_number} · ` : ""}{row.institute_email ?? "Unknown email"} → {row.result ?? "unknown"}
            {reasons ? ` · ${reasons}` : ""}
          </li>
        );
      })}
    </ul>
  );
}

function StagedRows({ data }: { data: AdminBulkUpsertPayload }) {
  return (
    <Card>
      <CardHeader><CardTitle>Staged rows</CardTitle></CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {data.staged.pending.length + data.staged.errored.length + data.staged.applied.length === 0 ? (
          <EmptyState message="No row is waiting for a user to sign in." />
        ) : (
          (["pending", "errored", "applied"] as const)
            .filter((state) => data.staged[state].length > 0)
            .map((state) => (
              <section key={state}>
                <h3 className="text-label-caps uppercase text-muted-foreground">{state} ({data.staged[state].length})</h3>
                <ul className="mt-gap-md flex flex-col gap-gap-md">
                  {data.staged[state].map((row) => (
                  <li key={row.id} className="flex flex-wrap items-center gap-gap-md rounded border border-border p-gap-md text-body-sm">
                    <span className="min-w-0 flex-1 text-foreground">{row.institute_email}{row.row_number ? ` · row ${row.row_number}` : ""}{row.error ? ` · ${row.error}` : ""}</span>
                    {state === "pending" ? (
                      <PreviewConfirm
                        command="delete_staged_row"
                        input={{ staged_row_id: row.id }}
                        title={`Delete staged row for ${row.institute_email}?`}
                        confirmLabel="Delete staged row"
                        destructive
                        trigger={<Button variant="destructive-ghost" size="sm">Delete</Button>}
                      />
                    ) : null}
                  </li>
                  ))}
                </ul>
              </section>
            ))
        )}
      </CardBody>
    </Card>
  );
}
