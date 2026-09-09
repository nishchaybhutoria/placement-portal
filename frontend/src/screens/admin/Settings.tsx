import { useState } from "react";

import { payload, type SettingsPayload } from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { ErrorState, ScreenSkeleton } from "@/components/ui/states";
import { formatDate } from "@/lib/date";

type Row = SettingsPayload["settings"][number];

/**
 * The settings whose defaults live in code and whose overrides live in the
 * database (LLD §11.3 `admin/settings`).
 *
 * Every key is listed whether or not a row exists for it, because a setting
 * with no override is still a setting somebody may need to find; the screen
 * says which value is in force and where it came from rather than showing an
 * empty table and leaving the default invisible.
 */
const KEYS = [
  {
    key: "strikes_per_penalty",
    label: "Strikes per penalty",
    hint: "How many strikes convert into one penalty. Blank means no threshold.",
    kind: "number" as const,
  },
  {
    key: "session_hours",
    label: "Session lifetime (hours)",
    hint: "How long a signed-in session stays valid.",
    kind: "number" as const,
  },
  {
    key: "ses_sender",
    label: "Notification sender address",
    hint: "The From address on every notification the portal sends.",
    kind: "text" as const,
  },
] as const;

export function Settings() {
  const screen = useScreen("admin/settings");

  if (screen.isPending) return <ScreenSkeleton variant="form" />;
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const rows = payload<SettingsPayload>(screen.data).settings ?? [];

  return (
    <>
      <PageHeader
        title="Settings"
        subtitle="Overrides for the values that would otherwise come from code defaults."
      />
      <Card>
        <CardHeader>
          <CardTitle>Portal settings</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-section-margin">
          {KEYS.map((definition) => (
            <SettingRow
              key={definition.key}
              definition={definition}
              row={rows.find((row) => row.key === definition.key)}
            />
          ))}
        </CardBody>
      </Card>
    </>
  );
}

function SettingRow({
  definition,
  row,
}: {
  definition: (typeof KEYS)[number];
  row: Row | undefined;
}) {
  const stored = row === undefined ? "" : String(row.value ?? "");
  const [draft, setDraft] = useState<string | null>(null);
  const save = useCommand("set_setting");
  const value = draft ?? stored;
  const dirty = draft !== null && draft !== stored;

  return (
    <div className="flex flex-col gap-gap-md">
      <div className="flex flex-wrap items-end gap-gap-lg">
        <Field label={definition.label} hint={definition.hint} className="min-w-64 flex-1">
          {(field) => (
            <Input
              {...field}
              type={definition.kind === "number" ? "number" : "text"}
              value={value}
              onChange={(event) => setDraft(event.target.value)}
            />
          )}
        </Field>
        <Button
          variant="primary"
          disabled={!dirty}
          loading={save.isPending}
          onClick={() =>
            save.mutate(
              {
                input: {
                  key: definition.key,
                  value:
                    definition.key === "strikes_per_penalty" && value === ""
                      ? null
                      : definition.kind === "number"
                        ? Number(value)
                        : value,
                },
              },
              { onSuccess: () => setDraft(null) },
            )
          }
        >
          Save
        </Button>
      </div>
      <p className="text-body-sm text-muted-foreground">
        {row
          ? `Overridden${row.updated_at ? ` on ${formatDate(row.updated_at)}` : ""}.`
          : "No override — the code default is in force."}
      </p>
      {save.isError ? <ErrorState error={save.error} title="Could not save" /> : null}
    </div>
  );
}
