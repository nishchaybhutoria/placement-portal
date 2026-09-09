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
