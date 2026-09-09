import { isValidElement } from "react";

import type {
  CompensationBlock,
  Funnel,
  PlacedFigure,
  Rate,
} from "@/api/payloads";
import { Card, CardBody, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/states";
import { cn } from "@/lib/cn";
import { counted } from "@/lib/text";

/**
 * The pieces every analytics surface shares, so one number is rendered one way
 * everywhere it appears.
 *
 * The formatting decisions here carry the ANA-1 rulings into the UI:
 * a rate always shows the fraction it came from, a compensation figure always
 * shows its coverage, and the placed split is always drawn as two levels that
 * sum. A number rendered without those is a number somebody can misquote.
 */

/** A rate as a percentage, with the fraction that produced it beneath. */
export function RateCell({ rate }: { rate: Rate }) {
  if (rate.ratio === null) {
    return (
      <span className="text-muted-foreground" title="No one to divide by">
        —
      </span>
    );
  }
  const percent = (Number(rate.ratio) * 100).toFixed(1);
  return (
    <span className="tabular">
      {percent}%{" "}
      {/* One text node, not five: a fraction split across nodes is invisible
          to anything reading the page by its text, tests included. */}
      <span className="text-body-sm text-muted-foreground">
        {`(${rate.numerator}/${rate.denominator})`}
      </span>
    </span>
  );
}

/** A compensation block, never shown without the coverage that qualifies it. */
export function CompensationCard({
  title,
  block,
}: {
  title: string;
  block: CompensationBlock;
}) {
  const unit = block.unit === "lpa" ? "LPA" : "₹/month";
  const uncovered = block.placed - block.covered;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-md">
        {block.covered === 0 ? (
          <p className="text-body-sm text-muted-foreground">
            No recorded compensation for placed students in this scope.
          </p>
        ) : (
          <>
            <dl className="grid grid-cols-2 gap-gap-md text-body-sm sm:grid-cols-4">
              <Stat label={`Median (${unit})`} value={block.median} />
              <Stat label={`Mean (${unit})`} value={block.mean} />
              <Stat label={`Min (${unit})`} value={block.min} />
              <Stat label={`Max (${unit})`} value={block.max} />
            </dl>
            {/* The gap between placed and covered is the caveat that keeps a
                median over three of forty from reading as the batch median. */}
            <p className="text-body-sm text-muted-foreground">
              From {block.covered} of {counted(block.placed, "placed student")}
              {uncovered > 0
                ? ` — ${uncovered} placed student${uncovered === 1 ? "" : "s"} ${
                    uncovered === 1 ? "has" : "have"
                  } no recorded figure`
                : ""}
              .
            </p>
          </>
        )}
      </CardBody>
    </Card>
  );
}

function Stat({ label, value }: { label: string; value: string | null }) {
  return (
    <div>
      <dt className="text-body-sm text-muted-foreground">{label}</dt>
      <dd className="tabular text-body-md font-semibold">{value ?? "—"}</dd>
    </div>
  );
}

/** The on-portal/external split, both levels, with their sums stated. */
export function PlacedSplit({ placed }: { placed: PlacedFigure }) {
  return (
    <div className="flex flex-col gap-gap-tight text-body-sm">
      <p className="tabular">
        <strong>{counted(placed.total, "student")}</strong> placed —{" "}
        <span>{placed.split.portal} on campus</span>,{" "}
        <span>{placed.split.external} external</span>
      </p>
      <p className="text-muted-foreground tabular">
        External: {placed.external_sources.ppo} PPO,{" "}
        {placed.external_sources.off_campus} off campus,{" "}
        {placed.external_sources.other} other
      </p>
      {placed.discarded_acceptances > 0 ? (
        <p className="text-muted-foreground">
          {placed.discarded_acceptances} further acceptance
          {placed.discarded_acceptances === 1 ? "" : "s"} not counted: each
          student is attributed to their most recent one.
        </p>
      ) : null}
    </div>
  );
}

/** registered → applied → offered → placed, plus both ANA-3 denominators. */
export function FunnelCards({ funnel }: { funnel: Funnel }) {
  return (
    <div className="grid grid-cols-2 gap-gap-md lg:grid-cols-4">
      <FunnelStat label="Registered" value={funnel.registered} />
      <FunnelStat label="Applied" value={funnel.applied} />
      <FunnelStat label="Offered" value={funnel.offered} />
      <FunnelStat label="Placed" value={funnel.placed.total} />
    </div>
  );
}

function FunnelStat({ label, value }: { label: string; value: number }) {
  return (
    <Card>
      <CardBody>
        <p className="text-body-sm text-muted-foreground">{label}</p>
        <p className="tabular text-headline-md font-semibold">{value}</p>
      </CardBody>
    </Card>
  );
}

/**
 * Both placement rates, in the order ANA-3 requires.
 *
 * The flat ANA-1 rate is the headline and the tag-adjusted one sits beneath it,
 * labelled: whoever quotes one number takes the first, and the first must be
 * the conservative one (the design review 4.30b).
 */
export function PlacementRates({ funnel }: { funnel: Funnel }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Placement rate</CardTitle>
      </CardHeader>
      <CardBody className="flex flex-col gap-gap-md">
        <div>
          <p className="text-body-sm text-muted-foreground">
            Placed ÷ all active registrations
          </p>
          <p className="text-headline-md font-semibold">
            <RateCell rate={funnel.placement_rate} />
          </p>
        </div>
        <div>
          <p className="text-body-sm text-muted-foreground">
            Seeking only — excludes higher studies, entrepreneurship and not
            seeking
          </p>
          <p className="text-body-md">
            <RateCell rate={funnel.placement_rate_seeking} />
          </p>
        </div>
      </CardBody>
    </Card>
  );
}

/** A plain table; every chart on these screens is paired with one. */
export function DataTable({
  headers,
  rows,
  caption,
}: {
  headers: string[];
  rows: (string | number | React.ReactNode)[][];
  caption?: string;
}) {
  if (rows.length === 0) {
    return <EmptyState message="No data is available for this view." />;
  }
  const numericColumns = headers.map((_, index) =>
    rows.some((row) => isNumericCell(row[index])),
  );
  return (
    <table className="w-full min-w-[32rem] border-collapse text-body-md">
      {caption ? <caption className="sr-only">{caption}</caption> : null}
      <thead>
        <tr className="border-b border-border bg-muted">
          {headers.map((header, index) => (
            <th
              key={header}
              className={cn(
                "px-table-cell-x py-table-cell-y text-label-caps uppercase text-muted-foreground",
                numericColumns[index] ? "text-right" : "text-left",
              )}
            >
              {header}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, index) => (
          <tr key={index} className="border-b border-border last:border-0 hover:bg-muted">
            {row.map((cell, cellIndex) => (
              <td
                key={cellIndex}
                className={cn(
                  "px-table-cell-x py-table-cell-y",
                  numericColumns[cellIndex] && "text-right tabular",
                )}
              >
                {cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function isNumericCell(cell: React.ReactNode): boolean {
  if (typeof cell === "number") return true;
  if (typeof cell === "string") return /^-?\d+(?:[.,/]\d+)*(?:%|\sLPA)?$/.test(cell);
  return isValidElement(cell) && cell.type === RateCell;
}
