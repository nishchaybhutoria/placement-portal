import type { HTMLAttributes } from "react";

import { cn } from "@/lib/cn";

/** DESIGN.md §8 "Card" — surface tier + 1px border, never a shadow. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded border border-border bg-card", className)} {...props} />;
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-gap-lg border-b border-border bg-muted px-container-padding py-gap-lg",
        className,
      )}
      {...props}
    />
  );
}

export function CardTitle({ className, ...props }: HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("text-headline-md text-foreground", className)} {...props} />;
}

export function CardBody({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-container-padding", className)} {...props} />;
}
