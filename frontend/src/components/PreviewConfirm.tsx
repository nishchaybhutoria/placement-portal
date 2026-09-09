import { useEffect, useState, type ReactNode } from "react";

import type { CommandInput, CommandName, CommandSummary, PreviewEvent } from "@/api/client";
import { useCommand, usePreview } from "@/api/useScreen";
import { cn } from "@/lib/cn";
import { humanise } from "@/lib/text";
import { useDebouncedValue } from "@/lib/useDebouncedValue";
import { Button } from "./ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "./ui/dialog";
import { Field } from "./ui/field";
import { Input, Select, Textarea } from "./ui/input";
import { ErrorState, Skeleton } from "./ui/states";

/**
 * The one shared destructive-action pattern (LLD §16, the build contract F1).
 *
 * dry run → render the server's summary and projected events → confirm. The
 * user never sees a confirmation the *client* composed: the text below the
 * fold is always what the server said would happen. Choice inputs feed back
 * into the input, so changing a choice re-runs the dry run rather than letting
 * the preview drift out of sync with what confirm will actually send.
 */

export interface Choice {
  name: string;
  label: string;
  kind?: "text" | "textarea" | "select" | "datetime" | "date" | "number";
  options?: readonly { value: string; label: string }[];
  required?: boolean;
  hint?: string;
  /** Seed an editable choice without forcing the operator to re-select it. */
  initialValue?: string;
  /** Show outcome-specific fields without retaining their hidden wire values. */
  visibleWhen?: { name: string; value: string };
  /** Convert a select's wire value before merging it into the typed input. */
  coerce?: "boolean";
}

/**
 * How long a typed choice sits still before the dialog dry-runs it again.
 *
 * Every change of the effective input re-runs the preview, which is what keeps
 * "previews never lie" true for a choice the operator edits. Per *keystroke*,
 * though, it would be a POST, so the debounce coalesces a burst of typing into
 * the one dry run that describes what Confirm will send; the effect below
 * aborts whatever it supersedes.
 *
 * This used to carry a second, sharper cost. The route limiter charged dry runs
 * against the same `(principal, command)` budget as the execution, so on a
 * command carrying `rate_limit="10/min"` the eleventh character of a reason
 * returned 429 — and because Confirm shared the bucket, typing the reason was
 * what exhausted the allowance for doing the thing. the design review §4.39 settled
 * that: the budget is a write budget, and a preview no longer spends it.
 */
const PREVIEW_DEBOUNCE_MS = 400;

/** A `datetime-local` string as the wire wants it, or null for "not set". */
function instant(value: string): string | null {
  return value ? new Date(value).toISOString() : null;
}

export interface PreviewConfirmProps<N extends CommandName> {
  command: N;
  input: CommandInput<N>;
  title: string;
  description?: string;
  trigger: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
  choices?: readonly Choice[];
  /** Command-specific controls that cannot be represented by a scalar field. */
  choiceContent?: ReactNode;
  /**
   * Render the dry run's summary instead of the generic key/value table.
   *
   * The default panel flattens an array to its length, which is right for
   * "rows: 12" and wrong for a payload the summary carries *because* the
   * operator has to read it -- merge's `contacts_dropped` is a list of records
   * that nothing un-merges. Such a command supplies its own renderer rather
   * than the panel guessing which arrays matter.
   */
  renderSummary?: (summary: CommandSummary<N>) => ReactNode;
  /** Normalize a merged form input (for example, mutually exclusive compensation fields). */
  transformInput?: (input: CommandInput<N>) => CommandInput<N>;
  onDone?: (summary: CommandSummary<N>) => void;
}

export function PreviewConfirm<N extends CommandName>({
  command,
  input,
  title,
  description,
  trigger,
  confirmLabel = "Confirm",
  destructive = false,
  choices = [],
  choiceContent,
  renderSummary,
  transformInput,
  onDone,
}: PreviewConfirmProps<N>) {
  const [open, setOpen] = useState(false);
  const [values, setValues] = useState<Record<string, string>>({});
  const preview = usePreview(command);
  const execute = useCommand(command);

  const choiceValue = (choice: Choice) =>
    values[choice.name] ?? choice.initialValue ?? String((input as Record<string, unknown>)[choice.name] ?? "");
  const visibleChoices = choices.filter((choice) => {
    if (!choice.visibleWhen) return true;
    const controlling = choices.find((item) => item.name === choice.visibleWhen!.name);
    const value = controlling
      ? choiceValue(controlling)
      : String((input as Record<string, unknown>)[choice.visibleWhen.name] ?? "");
    return value === choice.visibleWhen.value;
  });
  const missing = visibleChoices.filter((choice) => choice.required && !choiceValue(choice));
  const effectiveValues = Object.fromEntries(
    visibleChoices
      .filter((choice) => values[choice.name] !== undefined || choice.initialValue !== undefined)
      .map((choice) => {
        const value = choiceValue(choice);
        if (choice.coerce === "boolean") return [choice.name, value === "true"];
        if (choice.kind === "datetime") return [choice.name, instant(value)];
        return [choice.name, value];
      }),
  );
  const untransformed = { ...(input as object), ...effectiveValues } as CommandInput<N>;
  const merged = transformInput ? transformInput(untransformed) : untransformed;
  const previewReset = preview.reset;
  const previewMutate = preview.mutate;

  // Re-run the dry run whenever the effective input changes, so the summary on
  // screen always describes exactly what Confirm will send -- but a beat after
  // the operator stops typing, not once per character. `merged` is rebuilt
  // every render, so debounce its serialisation, which is what the effect keys
  // off anyway.
  const wire = JSON.stringify(merged);
  const settled = useDebouncedValue(wire, PREVIEW_DEBOUNCE_MS);
  // Between the last keystroke and the dry run that answers it, the panel on
  // screen describes an input Confirm would no longer send. Invariant 6 does
  // not bend for 400ms: the button waits with the preview.
  const previewPending = preview.isPending || settled !== wire;

  // Each run supersedes the last, so the cleanup aborts the dry run it
  // replaces: the answer to an input nobody is waiting for is cancelled on the
  // wire instead of racing the answer to the one that is (the design review §4.39).
  useEffect(() => {
    if (!open) return;
    if (missing.length > 0) {
      previewReset();
      return;
    }
    const controller = new AbortController();
    previewMutate({ input: JSON.parse(settled) as CommandInput<N>, signal: controller.signal });
    return () => controller.abort();
  }, [open, settled, missing.length, previewMutate, previewReset]);

  function close() {
    setOpen(false);
    setValues({});
    preview.reset();
    execute.reset();
  }

  function confirm() {
    execute.mutate(
      { input: merged },
      {
        onSuccess: (result) => {
          onDone?.(result.summary);
          close();
        },
      },
    );
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? setOpen(true) : close())}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>
            {description ?? "Review the server preview before confirming."}
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-gap-lg p-container-padding">
          {visibleChoices.length > 0 ? (
            <div className="flex flex-col gap-gap-lg">
              {visibleChoices.map((choice) => (
                <ChoiceField
                  key={choice.name}
                  choice={choice}
                  value={choiceValue(choice)}
                  onChange={(next) => setValues((prev) => ({ ...prev, [choice.name]: next }))}
                />
              ))}
            </div>
          ) : null}
          {choiceContent}

          {missing.length > 0 ? (
            <p className="text-body-sm text-muted-foreground">
              Fill in the fields above to see what this will do.
            </p>
          ) : previewPending ? (
            <div className="flex flex-col gap-gap-md">
              <Skeleton className="h-4 w-1/2" />
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ) : preview.isError ? (
            <ErrorState
              error={preview.error}
              title="This action was rejected"
              onRetry={() => preview.mutate({ input: merged })}
            />
          ) : preview.data ? (
            <PreviewPanel
              summary={preview.data.summary}
              events={preview.data.events}
              {...(renderSummary ? { render: () => renderSummary(preview.data.summary) } : {})}
            />
          ) : null}

          {execute.isError ? <ErrorState error={execute.error} title="Could not complete" /> : null}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={close} disabled={execute.isPending}>
            Cancel
          </Button>
          <Button
            variant={destructive ? "destructive" : "primary"}
            onClick={confirm}
            loading={execute.isPending}
            disabled={!preview.data || previewPending}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ChoiceField({
  choice,
  value,
  onChange,
}: {
  choice: Choice;
  value: string;
  onChange: (next: string) => void;
}) {
  return (
    <Field
      label={choice.label}
      {...(choice.required ? { required: true } : {})}
      {...(choice.hint ? { hint: choice.hint } : {})}
    >
      {(field) =>
        choice.kind === "textarea" ? (
          <Textarea {...field} value={value} onChange={(e) => onChange(e.target.value)} />
        ) : choice.kind === "datetime" || choice.kind === "date" || choice.kind === "number" ? (
          <Input
            {...field}
            type={choice.kind === "date" ? "date" : choice.kind === "number" ? "number" : "datetime-local"}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        ) : choice.kind === "select" ? (
          <Select {...field} value={value} onChange={(e) => onChange(e.target.value)}>
            <option value="">Select…</option>
            {(choice.options ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        ) : (
          <Input {...field} value={value} onChange={(e) => onChange(e.target.value)} />
        )
      }
    </Field>
  );
}

function PreviewPanel({
  summary,
  events,
  render: renderSummary,
}: {
  summary: unknown;
  events: PreviewEvent[];
  render?: () => ReactNode;
}) {
  // Identifiers are dropped rather than printed. A command summary echoes the
  // ids it was given, so "Cycle id 4b71c0de-…" tells the reader nothing they
  // did not just select by name — it only crowds out the lines that do say
  // what will happen.
  const rows = Object.entries((summary ?? {}) as Record<string, unknown>).filter(
    ([key]) => key !== "id" && !key.endsWith("_id") && !key.endsWith("_ids"),
  );
  const hasSummary = renderSummary !== undefined || rows.length > 0;
  // Nothing left to show once the ids are dropped, and no events either. Say
  // nothing: the dialog's own description states the effect, and a panel
  // announcing "nothing will change" over a command that plainly does would be
  // worse than the UUIDs it replaced.
  if (!hasSummary && events.length === 0) return null;
  return (
    <div className="flex flex-col gap-gap-lg rounded border border-border bg-muted p-gap-lg">
      {hasSummary ? (
        <div>
          <p className="text-label-caps uppercase text-muted-foreground">What will happen</p>
          {renderSummary ? (
            <div className="mt-gap-md">{renderSummary()}</div>
          ) : (
            <dl className="mt-gap-md grid grid-cols-2 gap-x-gap-lg gap-y-gap-tight text-body-md">
              {rows.map(([key, value]) => (
                <div key={key} className="contents">
                  <dt className="text-muted-foreground">{humanise(key)}</dt>
                  <dd className={cn("text-foreground", typeof value === "number" && "tabular")}>
                    {render(value)}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </div>
      ) : null}
      {events.length > 0 ? (
        <div>
          <p className="text-label-caps uppercase text-muted-foreground">
            {events.length} event{events.length === 1 ? "" : "s"}
          </p>
          <ul className="mt-gap-md flex flex-col gap-gap-tight text-body-sm text-foreground">
            {events.map((event, index) => (
              <li key={index}>
                <span className="font-semibold">{humanise(event.event_type)}</span>
                {event.from_status && event.to_status ? (
                  <span className="text-muted-foreground">
                    {" "}
                    — {humanise(event.from_status).toLowerCase()} →{" "}
                    {humanise(event.to_status).toLowerCase()}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}


function render(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (Array.isArray(value)) return value.length === 0 ? "—" : String(value.length);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
