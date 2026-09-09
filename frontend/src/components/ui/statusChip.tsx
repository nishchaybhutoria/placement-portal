import { cn } from "@/lib/cn";
import { statusMeta, type SemanticFamily, type StatusDomain } from "@/lib/status";

/**
 * DESIGN.md §8 "Status chip". A chip may not choose its own colour — the family
 * comes from the §4 mapping keyed by domain + value, so the same enum value can
 * never render two ways in two screens.
 */
const FAMILY_CLASSES: Record<SemanticFamily, string> = {
  success: "bg-success-subtle text-success border-success-border",
  warning: "bg-warning-subtle text-warning border-warning-border",
  danger: "bg-danger-subtle text-danger border-danger-border",
  info: "bg-info-subtle text-info border-info-border",
  neutral: "bg-neutral-subtle text-neutral border-neutral-border",
  brand: "bg-brand-subtle text-brand border-brand-border",
};

export interface StatusChipProps {
  domain: StatusDomain;
  value: string;
  className?: string;
}

export function StatusChip({ domain, value, className }: StatusChipProps) {
  const { label, family } = statusMeta(domain, value);
  return (
    <span
      className={cn(
        "inline-flex h-chip shrink-0 items-center whitespace-nowrap rounded-sm border px-gap-md text-label-caps uppercase",
        FAMILY_CLASSES[family],
        className,
      )}
    >
      {label}
    </span>
  );
}
