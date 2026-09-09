import { useState } from "react";

import { payload, type TemplatesPayload } from "@/api/payloads";
import { useCommand, useScreen } from "@/api/useScreen";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Field } from "@/components/ui/field";
import { Input, Select, Textarea } from "@/components/ui/input";
import { EmptyState, ErrorState, ScreenSkeleton } from "@/components/ui/states";

export function Templates() {
  const screen = useScreen("admin/templates");
  const [eventKey, setEventKey] = useState("offer_extended");
  const [cycleId, setCycleId] = useState("");

  if (screen.isPending) {
    return <ScreenSkeleton variant="form" />;
  }
  if (screen.isError) {
    return <ErrorState error={screen.error} onRetry={() => void screen.refetch()} />;
  }

  const data = payload<TemplatesPayload>(screen.data);
  const event = data.templates.find((item) => item.event_key === eventKey) ?? data.templates[0];
  if (!event || !event.global) {
    return (
      <>
        <PageHeader
          title="Notification templates"
          subtitle="Edit global copy, create cycle overrides, and disable individual events."
        />
        <Card>
          <CardBody>
            <EmptyState message="No notification templates are configured yet." />
          </CardBody>
        </Card>
      </>
    );
  }
  const override = event.overrides.find((item) => item.cycle_id === cycleId);
  const selected = cycleId ? (override ?? event.global) : event.global;

  return (
    <>
      <PageHeader
        title="Notification templates"
        subtitle="Edit global copy, create cycle overrides, and disable individual events."
      />
      <Card>
        <CardHeader>
          <CardTitle>Template editor</CardTitle>
        </CardHeader>
        <CardBody className="flex flex-col gap-gap-lg">
          <div className="grid gap-gap-lg md:grid-cols-2">
            <Field label="Event">
              {(field) => (
                <Select
                  {...field}
                  value={event.event_key}
                  onChange={(item) => setEventKey(item.target.value)}
                >
                  {data.templates.map((item) => (
                    <option key={item.event_key} value={item.event_key}>
                      {item.event_key}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
            <Field label="Scope" hint="A cycle override takes precedence over the global copy.">
              {(field) => (
                <Select
                  {...field}
                  value={cycleId}
                  onChange={(item) => setCycleId(item.target.value)}
                >
                  <option value="">Global default</option>
                  {data.cycles.map((cycle) => (
                    <option key={cycle.id} value={cycle.id}>
                      {cycle.name}
                    </option>
                  ))}
                </Select>
              )}
            </Field>
          </div>
          <p className="text-body-sm text-muted-foreground">
            Variables: {event.variables.map((variable) => `{${variable}}`).join(", ") || "none"}
          </p>
          {cycleId && !override ? (
            <p className="text-body-sm text-muted-foreground">
              No override yet — saving creates one from the global copy shown below.
            </p>
          ) : null}
          <TemplateForm
            key={`${event.event_key}:${cycleId}:${selected.id}`}
            eventKey={event.event_key}
            cycleId={cycleId || null}
            template={selected}
          />
        </CardBody>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Dead letters</CardTitle>
        </CardHeader>
        <CardBody>
          {data.dead_letters.length === 0 ? (
            <EmptyState message="No notification is waiting to be resent." />
          ) : (
            <div className="flex flex-col gap-gap-md">
              {data.dead_letters.map((letter) => (
                <DeadLetter key={letter.id} letter={letter} />
              ))}
            </div>
          )}
        </CardBody>
      </Card>
    </>
  );
}

type EditableTemplate = {
  id: string;
  subject: string;
  body: string;
  enabled: boolean;
};

function TemplateForm({
  eventKey,
  cycleId,
  template,
}: {
  eventKey: string;
  cycleId: string | null;
  template: EditableTemplate;
}) {
  const save = useCommand("update_template");
  const [subject, setSubject] = useState(template.subject);
  const [body, setBody] = useState(template.body);
  const [enabled, setEnabled] = useState(template.enabled);

  return (
    <div className="flex flex-col gap-gap-lg">
      <Field label="Subject">
        {(field) => (
          <Input {...field} value={subject} onChange={(item) => setSubject(item.target.value)} />
        )}
      </Field>
      <Field label="Body">
        {(field) => (
          <Textarea
            {...field}
            className="min-h-56"
            value={body}
            onChange={(item) => setBody(item.target.value)}
          />
        )}
      </Field>
      <label className="flex items-center gap-gap-md text-body-md">
        <Checkbox checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
        Enabled for this scope
      </label>
      <div>
        <Button
          variant="primary"
          loading={save.isPending}
          onClick={() =>
            save.mutate({
              input: {
                event_key: eventKey,
                cycle_id: cycleId,
                subject,
                body,
                enabled,
              },
            })
          }
        >
          Save template
        </Button>
      </div>
      {save.isError ? <ErrorState error={save.error} title="Could not save template" /> : null}
    </div>
  );
}

function DeadLetter({ letter }: { letter: TemplatesPayload["dead_letters"][number] }) {
  const resend = useCommand("resend_notification");
  return (
    <div className="flex flex-wrap items-center justify-between gap-gap-md rounded border border-border p-gap-md">
      <div>
        <p className="text-body-md font-medium">{letter.subject}</p>
        <p className="text-body-sm text-muted-foreground">
          {letter.recipient} · {letter.event_key} · {letter.attempts} attempts
        </p>
        {letter.last_error ? <p className="text-body-sm text-destructive">{letter.last_error}</p> : null}
      </div>
      <Button
        variant="secondary"
        loading={resend.isPending}
        onClick={() => resend.mutate({ input: { notification_id: letter.id } })}
      >
        Resend
      </Button>
    </div>
  );
}
