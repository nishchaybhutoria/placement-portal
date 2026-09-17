const LOCALE = "en-GB";

const DATE_FORMAT = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
});

const DATE_TIME_FORMAT = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const ZONED_DATE_TIME_FORMAT = new Intl.DateTimeFormat(LOCALE, {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
  timeZoneName: "short",
});

function parsed(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  // A date-only API value is a calendar date, not midnight UTC. Parsing it as
  // an instant can display the previous day west of UTC.
  const date =
    value instanceof Date
      ? value
      : /^\d{4}-\d{2}-\d{2}$/.test(value)
        ? new Date(`${value}T00:00:00`)
        : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Product-wide calendar-date format. */
export function formatDate(value: string | Date | null | undefined): string {
  const date = parsed(value);
  return date ? DATE_FORMAT.format(date) : "Date unavailable";
}

/** Product-wide date/time format for deadlines and audit events. */
export function formatDateTime(value: string | Date | null | undefined): string {
  const date = parsed(value);
  return date ? DATE_TIME_FORMAT.format(date) : "Time unavailable";
}

/** Interview and venue slots always state the viewer's timezone. */
export function formatZonedDateTime(value: string | Date | null | undefined): string {
  const date = parsed(value);
  return date ? ZONED_DATE_TIME_FORMAT.format(date) : "Time unavailable";
}

/** Formats an instant or date as a local `YYYY-MM-DDTHH:mm` string for `datetime-local` inputs. */
export function toLocalDateTimeString(value: string | Date | null | undefined): string {
  const date = parsed(value);
  if (!date) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Converts a `datetime-local` string to a UTC ISO string for wire commands, or null if empty. */
export function toInstant(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}
