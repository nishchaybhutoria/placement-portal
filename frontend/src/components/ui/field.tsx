import { useId, type ReactNode } from "react";

import { cn } from "@/lib/cn";

export interface FieldProps {
  label: string;
  /** Rendered below the control in `danger.fg`, and wires `aria-invalid`. */
  error?: string;
  hint?: string;
  required?: boolean;
  className?: string;
  children: (props: {
    id: string;
    "aria-invalid": boolean | undefined;
    "aria-describedby": string | undefined;
  }) => ReactNode;
}

/** Label above control (DESIGN.md §8), with the error/hint plumbing attached. */
export function Field({ label, error, hint, required, className, children }: FieldProps) {
  const id = useId();
  const messageId = error ?? hint ? `${id}-message` : undefined;
  return (
    <div className={cn("flex flex-col gap-gap-tight", className)}>
      <label htmlFor={id} className="text-body-sm font-semibold text-foreground">
        {label}
        {/* The space belongs to the label, not to the marker: the accessible
            name computation trims each element's own text, so a space kept
            inside the span renders but disappears from the name. */}
        {required ? (
          <>
            {" "}
            <span className="text-danger">*</span>
          </>
        ) : null}
      </label>
      {children({
        id,
        "aria-invalid": error ? true : undefined,
        "aria-describedby": messageId,
      })}
      {error ? (
        <p id={messageId} className="text-body-sm text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={messageId} className="text-body-sm text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
