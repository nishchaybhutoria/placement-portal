import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import {
  command,
  screen,
  me,
  type CommandInput,
  type CommandName,
  type CommandSummary,
  type Me,
  type Preview,
  type ScreenData,
  type ScreenId,
} from "./client";
import { screenKey } from "./queryClient";
import { screenDeps } from "./screenDeps";

export interface ScreenOptions {
  params?: Record<string, string>;
  query?: Record<string, string | number | boolean | undefined>;
  enabled?: boolean;
  /**
   * Hold the previous rows while a new query is in flight.
   *
   * For a search box the query is part of the key, so every new term is a
   * fresh, empty query — and the screens guard on `isPending`, which means the
   * whole list is replaced by a skeleton between terms. Opt in where a filter
   * *narrows* a list the reader is already looking at; leave it off where the
   * previous answer would be about something else entirely.
   */
  keepPrevious?: boolean;
}

/** One hook per screen read — LLD §16. */
export function useScreen<I extends ScreenId>(
  id: I,
  options: ScreenOptions = {},
): UseQueryResult<ScreenData<I>, Error> {
  const { params, query, enabled, keepPrevious } = options;
  return useQuery({
    queryKey: screenKey(id, params, query),
    queryFn: ({ signal }) => screen(id, params, { ...(query ? { query } : {}), signal }),
    ...(enabled === undefined ? {} : { enabled }),
    ...(keepPrevious ? { placeholderData: keepPreviousData } : {}),
  });
}

/** The `/me` bootstrap. Everything role-aware hangs off this one query. */
export function useMe(): UseQueryResult<Me, Error> {
  return useQuery({ queryKey: ["me"], queryFn: me, staleTime: 60_000 });
}

export interface CommandVariables<N extends CommandName> {
  input: CommandInput<N>;
  idempotencyKey?: string;
  /** Preview only: abort this dry run when a later one supersedes it. */
  signal?: AbortSignal;
}

/**
 * Execute a command and invalidate the screens it can change.
 *
 * Invalidation is by screen id only — the params are left off the match prefix
 * deliberately, so approving a membership in cycle A also drops the cached
 * cycle B board rather than leaving one stale tab behind.
 */
export function useCommand<N extends CommandName>(
  name: N,
): UseMutationResult<{ summary: CommandSummary<N> }, Error, CommandVariables<N>> {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ input, idempotencyKey }: CommandVariables<N>) =>
      command(name, input, idempotencyKey === undefined ? {} : { idempotencyKey }),
    onSuccess: async () => {
      await Promise.all(
        screenDeps(name).map((id) =>
          client.invalidateQueries({ queryKey: ["screen", id], exact: false }),
        ),
      );
      // Membership and profile commands can change what the nav is allowed to
      // show, so the bootstrap is always refreshed alongside.
      await client.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

/**
 * A dry run. Never invalidates anything — by definition it changed nothing.
 *
 * A caller that re-previews as its input changes passes the `signal` of a
 * controller it aborts on the next run, so a superseded dry run is cancelled
 * on the wire rather than racing the one that replaced it (the design review §4.39).
 */
export function usePreview<N extends CommandName>(
  name: N,
): UseMutationResult<Preview<N>, Error, CommandVariables<N>> {
  return useMutation({
    mutationFn: ({ input, signal }: CommandVariables<N>) =>
      command(name, input, signal ? { dryRun: true, signal } : { dryRun: true }),
  });
}
