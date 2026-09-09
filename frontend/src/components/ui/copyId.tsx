import { Check, Copy } from "lucide-react";
import { useEffect, useState } from "react";

import { cn } from "@/lib/cn";

/**
 * Hand over an identifier without printing it.
 *
 * Ids are how the machine names things and names are how people do, so screens
 * show the name. The id is still occasionally the thing somebody needs — to
 * quote in a ticket, to run a query — and this is the one way to get it, rather
 * than dumping a UUID into the page on the off chance.
 */
export function CopyId({ value, className }: { value: string; className?: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1500);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <button
      type="button"
      title={value}
      aria-label={copied ? "Identifier copied" : `Copy identifier ${value}`}
      onClick={() => {
        // Clipboard access is refused in insecure contexts and by permission;
        // an id nobody can copy is a minor disappointment, not an error state.
        void navigator.clipboard
          ?.writeText(value)
          .then(() => setCopied(true))
          .catch(() => setCopied(false));
      }}
      className={cn(
        "inline-flex items-center gap-gap-tight rounded px-gap-tight text-label-sm text-muted-foreground",
        "transition-colors hover:bg-muted hover:text-foreground",
        "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        className,
      )}
    >
      {copied ? (
        <Check aria-hidden className="h-3 w-3" />
      ) : (
        <Copy aria-hidden className="h-3 w-3" />
      )}
      {copied ? "Copied" : "Copy id"}
    </button>
  );
}
