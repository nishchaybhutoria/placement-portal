import type { KeyboardEvent } from "react";

import { cn } from "@/lib/cn";

/**
 * A controlled tab strip. Underline-and-weight rather than a filled pill,
 * because DESIGN.md §7 prohibits pills and §1 puts hierarchy in weight and
 * colour rather than in shape.
 */
export interface TabDefinition<Id extends string> {
  id: Id;
  label: string;
  /** Rendered after the label — a count, usually. Omit rather than pass 0. */
  badge?: number;
  disabled?: boolean;
  disabledReason?: string;
}

export function Tabs<Id extends string>({
  tabs,
  active,
  onChange,
  className,
}: {
  tabs: readonly TabDefinition<Id>[];
  active: Id;
  onChange: (id: Id) => void;
  className?: string;
}) {
  function moveFocus(event: KeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const list = event.currentTarget.closest('[role="tablist"]');
    const buttons = Array.from(
      list?.querySelectorAll<HTMLButtonElement>('[role="tab"]:not(:disabled)') ?? [],
    );
    const current = buttons.indexOf(event.currentTarget);
    if (current < 0 || buttons.length === 0) return;
    event.preventDefault();
    const target =
      event.key === "Home"
        ? buttons[0]
        : event.key === "End"
          ? buttons.at(-1)
          : buttons[(current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length];
    target?.focus();
    target?.click();
  }

  return (
    <div
      role="tablist"
      aria-orientation="horizontal"
      className={cn("flex gap-gap-lg overflow-x-auto border-b border-border", className)}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            disabled={tab.disabled}
            tabIndex={isActive ? 0 : -1}
            title={tab.disabled ? tab.disabledReason : undefined}
            onKeyDown={moveFocus}
            onClick={() => onChange(tab.id)}
            className={cn(
              "-mb-px flex items-center gap-gap-md border-b-2 px-gap-tight pb-gap-md pt-gap-md text-body-md transition-colors",
              "focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
              "disabled:cursor-not-allowed disabled:opacity-50",
              isActive
                ? "border-b-primary font-semibold text-foreground"
                : "border-b-transparent text-muted-foreground hover:text-foreground",
            )}
          >
            {tab.label}
            {tab.badge === undefined ? null : (
              <span className="tabular rounded-sm bg-muted px-gap-md text-body-sm text-muted-foreground">
                {tab.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
