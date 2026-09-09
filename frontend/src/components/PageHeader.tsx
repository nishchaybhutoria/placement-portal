import type { ReactNode } from "react";

import { cn } from "@/lib/cn";

/** Page title, optional subtitle and breadcrumb, and the page-level actions. */
export function PageHeader({
  title,
  subtitle,
  breadcrumb,
  actions,
  className,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  breadcrumb?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-col gap-gap-md", className)}>
      {breadcrumb ? (
        <nav className="text-body-sm text-muted-foreground">{breadcrumb}</nav>
      ) : null}
      <div className="flex flex-wrap items-start justify-between gap-gap-lg">
        <div className="min-w-0 flex-1">
          <h1 className="text-display text-foreground">{title}</h1>
          {subtitle ? (
            <p className="mt-gap-tight text-body-md text-muted-foreground">{subtitle}</p>
          ) : null}
        </div>
        {actions ? (
          <div className="flex max-w-full flex-wrap items-center gap-gap-md sm:justify-end">
            {actions}
          </div>
        ) : null}
      </div>
    </header>
  );
}
