import type { ReactNode } from "react";

import { ApiError } from "@/api/problem";
import { cn } from "@/lib/cn";
import { reasonText } from "@/lib/reasons";
import { Button } from "./button";

/** DESIGN.md §8 "Empty / loading / error states". */

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-sm bg-muted", className)} />;
}

/**
 * A page-load skeleton with the same title, card header, and row rhythm as the
 * screens it stands in for. Variants change geometry, never the loading idiom.
 */
export function ScreenSkeleton({
  variant = "cards",
}: {
  variant?: "cards" | "detail" | "form" | "table";
}) {
  const rows = variant === "table" ? 5 : 3;
  return (
    <div role="status" aria-label="Loading page" className="flex flex-col gap-section-margin">
      <span className="sr-only">Loading…</span>
      <div className="flex flex-col gap-gap-md">
        <Skeleton className="h-9 w-3/5 max-w-80" />
        <Skeleton className="h-4 w-2/5 max-w-96" />
      </div>
      <div className={cn("grid gap-gap-lg", variant === "detail" && "lg:grid-cols-[2fr_1fr]")}>
        {Array.from({ length: variant === "cards" || variant === "detail" ? 2 : 1 }, (_, card) => (
          <div key={card} className="overflow-hidden rounded border border-border bg-card">
            <div className="border-b border-border bg-muted px-container-padding py-gap-lg">
              <Skeleton className="h-6 w-40" />
            </div>
            <div className={cn("flex flex-col gap-gap-lg p-container-padding", variant === "form" && "sm:grid sm:grid-cols-2")}>
              {Array.from({ length: rows }, (_, row) => (
                <div key={row} className="flex flex-col gap-gap-md">
                  <Skeleton className="h-4 w-1/3" />
                  <Skeleton className={cn(variant === "form" ? "h-control w-full" : "h-8 w-full")} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div role="status" aria-label="Loading table" className="flex flex-col">
      <span className="sr-only">Loading…</span>
      <div className="grid grid-cols-4 gap-gap-lg border-b border-border bg-muted px-table-cell-x py-table-cell-y">
        {Array.from({ length: 4 }, (_, column) => (
          <Skeleton key={column} className="h-4 w-full" />
        ))}
      </div>
      {Array.from({ length: rows }, (_, row) => (
        <div key={row} className="grid grid-cols-4 gap-gap-lg border-b border-border px-table-cell-x py-table-cell-y last:border-0">
          <Skeleton className="h-5 w-4/5" />
          <Skeleton className="h-5 w-3/5" />
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-1/2 justify-self-end" />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({
  icon,
  message,
  action,
}: {
  icon?: ReactNode;
  message: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-gap-lg py-section-margin text-center">
      {icon ? <div className="text-muted-foreground">{icon}</div> : null}
      <p className="text-body-md text-muted-foreground">{message}</p>
      {action}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title,
  message,
  backHref,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  /** Deliberate copy for a local routing/validation failure, never raw exception text. */
  message?: string;
  backHref?: string;
}) {
  const apiError = error instanceof ApiError ? error : null;
  const resolvedTitle = title ?? errorTitle(apiError);
  const messages = apiError
    ? apiError.reasons.map((reason) => reasonText(reason.code, reason.human))
    : [message ?? "The page could not be displayed. Please try again."];
  const offersWayBack = Boolean(backHref) || apiError?.status === 403 || apiError?.status === 404;

  return (
    <div
      role="alert"
      className="flex flex-col gap-gap-md rounded border border-danger-border bg-danger-subtle p-container-padding"
    >
      <p className="text-body-md font-semibold text-danger">{resolvedTitle}</p>
      <ul className="flex flex-col gap-gap-tight text-body-md text-foreground">
        {messages.map((message, index) => (
          <li key={`${message}:${index}`}>{message}</li>
        ))}
      </ul>
      {apiError?.requestId ? (
        <p className="text-body-sm text-muted-foreground">
          Reference: <code>{apiError.requestId}</code>
        </p>
      ) : null}
      {offersWayBack ? (
        <p className="text-body-sm text-muted-foreground">
          The link may be out of date, or this record may be outside your access.
        </p>
      ) : null}
      {onRetry || offersWayBack ? (
        <div className="flex flex-wrap gap-gap-md">
          {onRetry ? (
            <Button variant="secondary" size="sm" onClick={onRetry}>
              Retry
            </Button>
          ) : null}
          {offersWayBack ? (
            <Button variant="secondary" size="sm" asChild>
              <a href={backHref ?? "/"}>{backHref ? "Go back" : "Back to home"}</a>
            </Button>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function errorTitle(error: ApiError | null): string {
  if (error?.status === 403) return "You cannot access this page";
  if (error?.status === 404) return "Page not found";
  if (error?.status === 429) return "Too many requests";
  if (error && error.status >= 500) return "The service is unavailable";
  return "Something went wrong";
}
