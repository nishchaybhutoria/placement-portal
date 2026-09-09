import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

/**
 * The chart layer, and the only place in the frontend that decides how a chart
 * looks.
 *
 * Two rules hold here and are the reason this file exists:
 *
 * 1. **Every colour is a design token.** Recharts takes colours as strings, so
 *    the temptation is a hex literal per series — which `make forbid` rejects
 *    outright, and which would drift from the rest of the app in dark mode
 *    anyway. `hsl(var(--token))` is the sanctioned reference form (the gate
 *    blanks it before looking for literals), so a chart repaints with the
 *    theme like every other surface.
 * 2. **Every chart ships beside its table.** ANA-2 asks for readable,
 *    exportable figures, and a chart alone is neither: it cannot be copied
 *    into a filing, read by a screen reader, or checked against a total. The
 *    chart is the glance; the table underneath it is the record. Callers pair
 *    them; `ChartFrame` exists to make the pairing the easy thing to write.
 */

/** Categorical series colours, in the order a chart should consume them. */
export const SERIES = [
  "hsl(var(--accent))",
  "hsl(var(--primary))",
  "hsl(var(--info))",
  "hsl(var(--success))",
  "hsl(var(--warning))",
  "hsl(var(--neutral))",
] as const;

/** Semantic colours for the funnel, which is a sequence rather than a set. */
export const FUNNEL_COLOURS = {
  registered: "hsl(var(--neutral))",
  applied: "hsl(var(--info))",
  offered: "hsl(var(--primary))",
  placed: "hsl(var(--success))",
} as const;

/** On-portal versus external, used wherever the ANA-1 split is drawn. */
export const SPLIT_COLOURS = {
  portal: "hsl(var(--primary))",
  external: "hsl(var(--accent))",
  ppo: "hsl(var(--accent))",
  off_campus: "hsl(var(--info))",
  other: "hsl(var(--neutral))",
} as const;

const AXIS = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";
const SURFACE = "hsl(var(--popover))";
const SURFACE_TEXT = "hsl(var(--popover-foreground))";

const tooltipStyle = {
  backgroundColor: SURFACE,
  border: `1px solid ${GRID}`,
  borderRadius: "var(--radius)",
  color: SURFACE_TEXT,
  fontSize: "0.75rem",
};

const axisProps = {
  stroke: AXIS,
  fontSize: 11,
  tickLine: false,
  axisLine: { stroke: GRID },
} as const;

export interface Datum {
  label: string;
  [key: string]: string | number | null;
}

/**
 * A chart and its table, in that order, sharing one caption.
 *
 * The table is not optional and not collapsed behind a toggle: a coordinator
 * checking a figure against a total should not have to find a control first.
 */
export function ChartFrame({
  title,
  description,
  chart,
  table,
}: {
  title: string;
  description?: string;
  chart: React.ReactNode;
  table: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-gap-md" aria-label={title}>
      <div>
        <h3 className="text-body-md font-semibold">{title}</h3>
        {description ? (
          <p className="text-body-sm text-muted-foreground">{description}</p>
        ) : null}
      </div>
      <div className="h-56 w-full" role="img" aria-label={`${title} (chart)`}>
        {chart}
      </div>
      <div className="overflow-x-auto">{table}</div>
    </section>
  );
}

/** A bar per category, each bar its own colour. */
export function CategoryBars({
  data,
  valueKey,
  colours,
}: {
  data: Datum[];
  valueKey: string;
  colours?: readonly string[];
}) {
  const palette = colours ?? SERIES;
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} interval={0} angle={-15} textAnchor="end" height={48} />
        <YAxis {...axisProps} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: GRID, opacity: 0.25 }} />
        <Bar dataKey={valueKey} radius={[2, 2, 0, 0]}>
          {data.map((row, index) => (
            <Cell key={row.label} fill={palette[index % palette.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Several named series over the same categories, stacked or grouped. */
export function SeriesBars({
  data,
  series,
  stacked = false,
}: {
  data: Datum[];
  series: { key: string; label: string; colour: string }[];
  stacked?: boolean;
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} interval={0} angle={-15} textAnchor="end" height={48} />
        <YAxis {...axisProps} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: GRID, opacity: 0.25 }} />
        <Legend wrapperStyle={{ fontSize: "0.7rem", color: AXIS }} />
        {series.map((entry) => (
          <Bar
            key={entry.key}
            dataKey={entry.key}
            name={entry.label}
            fill={entry.colour}
            stackId={stacked ? "one" : undefined}
            radius={stacked ? undefined : [2, 2, 0, 0]}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** A trend over time, one line per named series. */
export function TrendLines({
  data,
  series,
}: {
  data: Datum[];
  series: { key: string; label: string; colour: string }[];
}) {
  return (
    <ResponsiveContainer width="100%" height="100%">
      <LineChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
        <XAxis dataKey="label" {...axisProps} />
        <YAxis {...axisProps} allowDecimals={false} />
        <Tooltip contentStyle={tooltipStyle} />
        <Legend wrapperStyle={{ fontSize: "0.7rem", color: AXIS }} />
        {series.map((entry) => (
          <Line
            key={entry.key}
            type="monotone"
            dataKey={entry.key}
            name={entry.label}
            stroke={entry.colour}
            strokeWidth={2}
            dot={false}
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}
