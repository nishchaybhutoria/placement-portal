import { useState, type ReactNode } from "react";

import { cn } from "@/lib/cn";
import { Button } from "./ui/button";
import { Textarea } from "./ui/input";

/**
 * The shared bulk-selection bar (the build contract F1): selection count, a
 * paste-identifiers box, and the action buttons for the current screen.
 *
 * Pasted identifiers are *added* to the selection rather than replacing it, and
 * the count is always of the resolved selection — the server is what decides
 * whether an identifier matched (`unmatched_identifier`), so this component
 * never claims a paste succeeded.
 */
export interface BulkBarProps {
  selected: readonly string[];
  onChange: (next: string[]) => void;
  /** Buttons for this screen; usually `<PreviewConfirm>` triggers. */
  actions?: ReactNode;
  /** What the identifiers are, for the placeholder — e.g. "roll numbers". */
  identifierLabel?: string;
  className?: string;
}

export function BulkBar({
  selected,
  onChange,
  actions,
  identifierLabel = "identifiers",
  className,
}: BulkBarProps) {
  const [pasting, setPasting] = useState(false);
  const [text, setText] = useState("");

  function addPasted() {
    const parsed = text
      .split(/[\s,;]+/)
      .map((token) => token.trim())
      .filter(Boolean);
    onChange([...new Set([...selected, ...parsed])]);
    setText("");
    setPasting(false);
  }

  return (
    <div
      className={cn(
        "flex flex-col gap-gap-md rounded border border-border bg-card p-gap-lg",
        className,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-gap-md">
        <div className="flex items-center gap-gap-lg">
          <span className="text-body-md text-foreground">
            <span className="tabular font-semibold">{selected.length}</span> selected
          </span>
          {selected.length > 0 ? (
            <Button variant="link" size="sm" onClick={() => onChange([])}>
              Clear
            </Button>
          ) : null}
          <Button variant="ghost" size="sm" onClick={() => setPasting((open) => !open)}>
            {pasting ? "Hide paste box" : `Paste ${identifierLabel}`}
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-gap-md">{actions}</div>
      </div>

      {pasting ? (
        <div className="flex flex-col gap-gap-md">
          <Textarea
            aria-label={`Paste ${identifierLabel}`}
            placeholder={`One per line, or separated by commas`}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="flex items-center gap-gap-md">
            <Button variant="secondary" size="sm" onClick={addPasted} disabled={!text.trim()}>
              Add to selection
            </Button>
            <p className="text-body-sm text-muted-foreground">
              Identifiers that match nothing are reported by the server when you confirm.
            </p>
          </div>
        </div>
      ) : null}
    </div>
  );
}
