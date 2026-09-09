import { useEffect, useState } from "react";

import { payload, type MeProfilePayload } from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { PreviewConfirm } from "@/components/PreviewConfirm";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input, Select } from "@/components/ui/input";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDate } from "@/lib/date";

const NUMBER_FIELDS = new Set([
  "graduating_year",
  "cpi",
  "active_backlogs",
  "total_backlogs",
  "tenth_percent",
  "tenth_year",
  "twelfth_percent",
  "twelfth_year",
]);
const URL_FIELDS = new Set(["github_url", "linkedin_url", "portfolio_url"]);

export function Profile() {
  const screen = useScreen("me/profile");
  if (screen.isPending) return <ScreenSkeleton variant="form" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }
  const data = payload<MeProfilePayload>(screen.data);
  return (
    <>
      <PageHeader
        title="My profile"
        subtitle={
          data.declared_at
            ? `Declared ${formatDate(data.declared_at)}. Locked fields now belong to the administration.`
            : "Declare this enrollment once, then keep your own contact and link fields current."
        }
      />
      <ProfileFields data={data} />
      <ResumeLibrary data={data} />
    </>
  );
}

function ProfileFields({ data }: { data: MeProfilePayload }) {
  const declared = data.declared_at !== null;
  const declare = useCommand("declare_profile");
  const update = useCommand("update_student_fields");
  const [draft, setDraft] = useState<Record<string, unknown>>({});
  const values = { ...data.values, ...draft };
  // Which fields are editable is the server's answer, carried per field: an
  // admin-managed column is still the student's to supply until it first holds
  // a value (the design review §4.33). Deriving it here from `owner` and `declared_at`
  // is how the form came to show a locked box for a field the command would
  // have accepted.
  const editable = data.fields.filter((field) => field.editable);
  const locked = data.fields.filter((field) => !field.editable);
  const mutation = declared ? update : declare;

  function save() {
    // Only what the student actually filled in. Sending `null` for an untouched
    // box is what used to write NULL over a column default at declaration —
    // and, before §4.33, into a field they could then never correct.
    const fields = declared
      ? draft
      : Object.fromEntries(
          editable
            .map((field) => [field.key, values[field.key]] as const)
            .filter(([, value]) => value !== null && value !== undefined && value !== ""),
        );
    mutation.mutate(
      {
        input: {
          enrollment_id: data.enrollment.id,
          fields,
        } as never,
      },
      { onSuccess: () => setDraft({}) },
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Enrollment details</CardTitle>
        <span className="text-body-sm text-muted-foreground">
          {data.enrollment.institute_email}
        </span>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {mutation.isError ? <ErrorState error={mutation.error} title="Could not save profile" /> : null}
        {locked.length > 0 ? (
          <dl className="grid gap-gap-lg rounded border border-border bg-muted p-gap-lg sm:grid-cols-2">
            {locked.map((field) => (
              <div key={field.key}>
                <dt className="text-body-sm text-muted-foreground">{field.label}</dt>
                <dd className="text-body-md text-foreground">
                  {displayValue(field.key, values[field.key], data)}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
        <div className="grid gap-gap-lg sm:grid-cols-2">
          {editable
            // PRO-1 asks the second major only of the students who have one,
            // and the server refuses a secondary branch from anyone else, so
            // the field appears when the answer does.
            .filter(
              (field) =>
                !["secondary_program_id", "secondary_branch_id"].includes(field.key) ||
                values["is_dual_degree"] ||
                (field.key === "secondary_branch_id" && values["is_dual_major"]),
            )
            .map((field) => (
              <ProfileField
                key={field.key}
                field={field}
                value={values[field.key]}
                allValues={values}
                data={data}
                onChange={(value) => setDraft((current) => ({ ...current, [field.key]: value }))}
                onSiblingChange={(key, value) =>
                  setDraft((current) => ({ ...current, [key]: value }))
                }
              />
            ))}
        </div>
        <div>
          <Button
            loading={mutation.isPending}
            disabled={declared && Object.keys(draft).length === 0}
            onClick={save}
          >
            {declared ? "Save profile" : "Declare profile"}
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}

function ProfileField({
  field,
  value,
  allValues,
  data,
  onChange,
  onSiblingChange,
}: {
  field: MeProfilePayload["fields"][number];
  value: unknown;
  allValues: Record<string, unknown>;
  data: MeProfilePayload;
  onChange: (value: unknown) => void;
  /** Clear a field this one governs, so the pair cannot contradict itself. */
  onSiblingChange?: (key: string, value: unknown) => void;
}) {
  const stringValue = value === null || value === undefined ? "" : String(value);
  const taxonomy = taxonomyFor(field.key);
  if (taxonomy) {
    let options = data.taxonomies[taxonomy];
    if (field.key === "primary_branch_id" || field.key === "secondary_branch_id") {
      const program = String(
        field.key === "secondary_branch_id" && allValues.is_dual_degree
          ? allValues.secondary_program_id ?? ""
          : allValues.program_id ?? "",
      );
      const admitted = new Set(
        data.program_branches
          .filter((row) => row.program_id === program)
          .map((row) => row.branch_id),
      );
      if (admitted.size > 0) options = options.filter((option) => admitted.has(option.id));
    }
    return (
      <Field label={field.label}>
        {(input) => (
          <Select {...input} value={stringValue} onChange={(event) => onChange(event.target.value || null)}>
            <option value="">None</option>
            {options.map((option) => <option key={option.id} value={option.id}>{option.name}</option>)}
          </Select>
        )}
      </Field>
    );
  }
  if (field.key === "is_dual_major" || field.key === "is_dual_degree") {
    const dualMajor = field.key === "is_dual_major";
    return (
      <Field
        label={field.label}
        hint={
          dualMajor
            ? "Two majors within the same primary degree."
            : "A BTech followed by an MTech or MSc in the same enrollment."
        }
      >
        {() => (
          <label className="flex h-control items-center gap-gap-md text-body-md text-foreground">
            <Checkbox
              checked={value === true}
              onChange={(event) => {
                // Turning it off clears the second major with it; leaving a
                // stale branch behind is the contradiction the server rejects.
                onChange(event.target.checked);
                if (event.target.checked) {
                  onSiblingChange?.(
                    dualMajor ? "is_dual_degree" : "is_dual_major",
                    false,
                  );
                  if (dualMajor) onSiblingChange?.("secondary_program_id", null);
                } else {
                  onSiblingChange?.("secondary_branch_id", null);
                  if (!dualMajor) onSiblingChange?.("secondary_program_id", null);
                }
              }}
            />
            {dualMajor
              ? "I am completing a dual major"
              : "I am completing a dual degree"}
          </label>
        )}
      </Field>
    );
  }
  if (field.key === "gender") {
    return (
      <Field label={field.label}>
        {(input) => (
          <Select {...input} value={stringValue} onChange={(event) => onChange(event.target.value || null)}>
            <option value="">Select…</option>
            <option value="male">Male</option>
            <option value="female">Female</option>
            <option value="other">Other</option>
          </Select>
        )}
      </Field>
    );
  }
  return (
    <Field label={field.label}>
      {(input) => (
        <Input
          {...input}
          type={NUMBER_FIELDS.has(field.key) ? "number" : URL_FIELDS.has(field.key) ? "url" : field.key === "personal_email" ? "email" : "text"}
          step={field.key === "cpi" || field.key.includes("percent") ? "0.01" : undefined}
          value={stringValue}
          onChange={(event) => onChange(event.target.value === "" ? null : event.target.value)}
        />
      )}
    </Field>
  );
}

function taxonomyFor(key: string): "programs" | "branches" | "minors" | null {
  if (key === "program_id" || key === "secondary_program_id") return "programs";
  if (key === "primary_branch_id" || key === "secondary_branch_id") return "branches";
  if (key === "minor1_id" || key === "minor2_id") return "minors";
  return null;
}

function displayValue(key: string, value: unknown, data: MeProfilePayload): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (value === null || value === undefined || value === "") return "—";
  const taxonomy = taxonomyFor(key);
  if (taxonomy) return data.taxonomies[taxonomy].find((item) => item.id === value)?.name ?? String(value);
  return String(value);
}

function ResumeLibrary({ data }: { data: MeProfilePayload }) {
  const add = useCommand("add_resume");
  const update = useCommand("update_resume");
  const makeDefault = useCommand("set_default_resume");
  const [label, setLabel] = useState("");
  const [url, setUrl] = useState("");
  const [isDefault, setIsDefault] = useState(data.resumes.length === 0);
  const [editing, setEditing] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState<string | null>(data.resumes[0]?.id ?? null);
  const selectedPreview = data.resumes.find((resume) => resume.id === previewing);

  useEffect(() => {
    if (previewing && !data.resumes.some((resume) => resume.id === previewing)) {
      setPreviewing(data.resumes[0]?.id ?? null);
    }
  }, [data.resumes, previewing]);

  function reset() {
    setLabel("");
    setUrl("");
    setEditing(null);
    setIsDefault(false);
  }

  function save() {
    if (editing) {
      update.mutate(
        { input: { enrollment_id: data.enrollment.id, resume_id: editing, label, drive_url: url } },
        { onSuccess: reset },
      );
    } else {
      add.mutate(
        { input: { enrollment_id: data.enrollment.id, label, drive_url: url, is_default: isDefault } },
        { onSuccess: reset },
      );
    }
  }

  return (
    <Card>
      <CardHeader><CardTitle>Resume library</CardTitle></CardHeader>
      <CardBody className="flex flex-col gap-gap-lg">
        {add.isError || update.isError || makeDefault.isError ? (
          <ErrorState error={add.error ?? update.error ?? makeDefault.error} title="Could not update resumes" />
        ) : null}
        <div className="grid gap-gap-lg sm:grid-cols-2">
          <Field label="Label" required>
            {(field) => <Input {...field} value={label} onChange={(event) => setLabel(event.target.value)} />}
          </Field>
          <Field label="Google Drive / Docs file link" required>
            {(field) => <Input {...field} type="url" value={url} onChange={(event) => setUrl(event.target.value)} />}
          </Field>
        </div>
        {!editing ? (
          <label className="flex items-center gap-gap-md text-body-md text-foreground">
            <Checkbox checked={isDefault} onChange={(event) => setIsDefault(event.target.checked)} />
            Make this the default resume
          </label>
        ) : null}
        <div className="flex gap-gap-md">
          <Button loading={add.isPending || update.isPending} disabled={!label.trim() || !url.trim()} onClick={save}>
            {editing ? "Save resume" : "Add resume"}
          </Button>
          {editing ? <Button variant="ghost" onClick={reset}>Cancel</Button> : null}
        </div>

        {data.resumes.length === 0 ? (
          <EmptyState message="No resume saved. A resume is required before joining a cycle." />
        ) : (
          <ul className="flex flex-col gap-gap-md">
            {data.resumes.map((resume) => (
              <li key={resume.id} className="flex flex-wrap items-center gap-gap-md rounded border border-border p-gap-lg">
                <div className="min-w-0 flex-1">
                  <p className="text-body-md font-medium text-foreground">{resume.label}{resume.is_default ? " · Default" : ""}</p>
                  <a href={resume.drive_url} target="_blank" rel="noreferrer" className="break-all text-body-sm text-accent hover:underline">{resume.drive_url}</a>
                </div>
                <Button variant="ghost" size="sm" onClick={() => setPreviewing(resume.id)}>Preview</Button>
                <Button variant="ghost" size="sm" onClick={() => { setEditing(resume.id); setLabel(resume.label); setUrl(resume.drive_url); }}>Edit</Button>
                {!resume.is_default ? (
                  <Button variant="secondary" size="sm" loading={makeDefault.isPending} onClick={() => makeDefault.mutate({ input: { enrollment_id: data.enrollment.id, resume_id: resume.id } })}>Make default</Button>
                ) : null}
                <PreviewConfirm
                  command="delete_resume"
                  input={{ enrollment_id: data.enrollment.id, resume_id: resume.id }}
                  title={`Delete ${resume.label}?`}
                  description="Applications keep the URL they copied. A membership using this as its default is cleared, as the preview reports."
                  confirmLabel="Delete resume"
                  destructive
                  trigger={<Button variant="destructive-ghost" size="sm">Delete</Button>}
                />
              </li>
            ))}
          </ul>
        )}
        {selectedPreview ? (
          <iframe
            title={`Preview of ${selectedPreview.label}`}
            src={selectedPreview.preview_url}
            className="h-[520px] w-full rounded border border-border bg-card"
          />
        ) : null}
      </CardBody>
    </Card>
  );
}
