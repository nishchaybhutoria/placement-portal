import { QueryClient } from "@tanstack/react-query";

import { ApiError, UnauthenticatedError } from "./problem";

/**
 * A rejected command is a *domain answer*, not a transport failure — retrying
 * it just asks the server the same question again. Only genuine network faults
 * and 5xx are worth a second attempt.
 */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof UnauthenticatedError) return false;
  if (error instanceof ApiError && error.status < 500) return false;
  return failureCount < 2;
}

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        // Screens are server-composed views; a short window keeps navigation
        // snappy without ever showing data older than the user's last write
        // (writes invalidate explicitly via SCREEN_DEPS).
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}

/** Query key for a screen read. Kept in one place so invalidation can match it. */
export function screenKey(
  id: string,
  params?: Record<string, string>,
  query?: Record<string, unknown>,
): readonly unknown[] {
  return ["screen", id, params ?? {}, query ?? {}];
}
