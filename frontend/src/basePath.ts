const configuredBase = import.meta.env.BASE_URL;

/** Public path at which this frontend is mounted, without a trailing slash. */
export const APP_BASE = configuredBase === "/" ? "" : configuredBase.replace(/\/$/, "");

/** Prefix an application-owned absolute path with the frontend mount path. */
export function appUrl(path: string): string {
  const absolute = path.startsWith("/") ? path : `/${path}`;
  return `${APP_BASE}${absolute}`;
}
