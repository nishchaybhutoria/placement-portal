"""ANA-3 -- the canned per-batch/per-program report.

**Provisional.**  ANA-3 says the standard column set is refined against the
office's exact NIRF and RTI formats "when those documents surface", and they
have not.  What ships is the column set the specification names, in the order
it names them, carrying an explicit `provisional` flag and a note saying so, so
that nobody downstream mistakes it for a format that has been agreed with
anybody.  When the real formats arrive, this module changes and nothing else
does, because every figure it prints is an ANA-1 metric rather than a query
written for the report.

The one decision that is not the specification's is column *order*, and it is
deliberate: `placement_rate` -- ANA-1's flat placed-over-registered -- is the
headline, and the outcome-tag-adjusted `placement_rate_seeking` sits after it,
clearly labelled.  Whoever pastes this table into a filing takes the first
number, and the first number should be the conservative one (the design review 4.30b).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast
from uuid import UUID

import sqlalchemy as sa

from app.modules.analytics import metrics
from app.modules.analytics.metrics import Executor, MetricFilters

#: The provisional standard column set, in the order ANA-3 lists it, with the
#: two honest-denominator columns placed where they cannot be mistaken for the
#: headline.  Each entry is (key, human label).
REPORT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("batch", "Batch"),
    ("program", "Programme"),
    ("registered", "Registered"),
    ("placed_on_campus", "Placed on campus"),
    ("placed_ppo", "Placed via PPO"),
    ("placed_off_campus", "Placed off campus"),
    ("placed_other_external", "Placed (other external)"),
    ("placed_total", "Placed (total)"),
    ("placement_rate", "Placement rate"),
    ("median_ctc_lpa", "Median CTC (LPA)"),
    ("mean_ctc_lpa", "Mean CTC (LPA)"),
    ("compensation_covered", "Placed with a recorded CTC"),
    ("higher_studies", "Higher studies"),
    ("entrepreneurship", "Entrepreneurship"),
    ("not_seeking", "Not seeking placement"),
    ("registered_seeking", "Registered (seeking only)"),
    ("placement_rate_seeking", "Placement rate (seeking only)"),
)

PROVISIONAL_NOTE = (
    "Provisional column set (Behavior ANA-3). The office's NIRF and RTI "
    "formats were not available when this was built, so these are the columns "
    "the specification names rather than a format agreed with the office. "
    "'Placement rate' is placed over all active registrations; the "
    "seeking-only rate excludes members tagged higher studies, "
    "entrepreneurship, or not seeking, and is shown separately rather than in "
    "place of it."
)

#: outcome_tag_t.  All three mean "not seeking a placement", which is why the
#: seeking denominator is the absence of a tag rather than a list of them.
OUTCOME_TAGS: tuple[str, ...] = ("higher_studies", "entrepreneurship", "not_seeking")


async def _outcome_tags(
    executor: Executor, filters: MetricFilters
) -> dict[UUID, str | None]:
    """The tag standing against each active membership in scope."""
    clause = "TRUE"
    params: dict[str, object] = {}
    if filters.cycle_ids is not None:
        clause = "m.cycle_id = ANY(:cycle_ids)"
        params["cycle_ids"] = list(filters.cycle_ids)
    rows = (
        await executor.execute(
            sa.text(
                "SELECT m.enrollment_id, CAST(m.outcome_tag AS text) AS tag "
                f"FROM cycle_memberships m WHERE m.status = 'active' AND {clause}"
            ),
            params,
        )
    ).mappings().all()
    return {
        cast(UUID, row["enrollment_id"]): (
            None if row["tag"] is None else str(row["tag"])
        )
        for row in rows
    }


async def batch_report(
    executor: Executor,
    filters: MetricFilters,
    *,
    program_labels: Mapping[str, str],
) -> dict[str, object]:
    """One row per (batch, programme), plus the total row.

    The counts are partitions of cohorts computed once, so every row and the
    total agree with the cycle dashboards by construction.  Compensation is the
    exception -- an aggregation cannot be partitioned in Python -- so it is
    asked per group, and only for groups that placed somebody.
    """
    computed = await metrics.funnel(executor, filters)
    everyone = (
        computed.registered.ids
        | computed.applied.ids
        | computed.offered.ids
        | computed.placed.ids
    )
    batches = await metrics.dimension_of(executor, everyone, "p.graduating_year")
    programs = await metrics.dimension_of(executor, everyone, "p.program_id")
    tags = await _outcome_tags(executor, filters)

    groups: dict[tuple[str, str], set[UUID]] = {}
    for enrollment_id in computed.registered.ids | computed.placed.ids:
        # SPEC-GAP (the design review 4.30g): ANA-3 says "per batch" and the only
        # representable batch is graduating_year, which is nullable.  Rows
        # without one group under `unknown` and stay in the totals rather than
        # being filtered out of a denominator nobody re-checks.
        key = (
            batches.get(enrollment_id) or metrics.UNKNOWN_BUCKET,
            programs.get(enrollment_id) or metrics.UNKNOWN_BUCKET,
        )
        groups.setdefault(key, set()).add(enrollment_id)

    rows: list[dict[str, object]] = []
    for batch, program in sorted(groups):
        members = groups[(batch, program)]
        registered = members & computed.registered.ids
        placed = members & computed.placed.ids
        seeking = frozenset(
            enrollment_id
            for enrollment_id in registered
            if tags.get(enrollment_id) is None
        )
        scoped = filters.narrow(
            graduating_year=None if batch == metrics.UNKNOWN_BUCKET else int(batch),
            program_id=None if program == metrics.UNKNOWN_BUCKET else UUID(program),
        )
        compensation = (
            await metrics.compensation(executor, scoped, outcome="placement")
            if placed
            else None
        )
        by_source = {
            source: len(members & ids)
            for source, ids in computed.placed.by_source.items()
        }
        rows.append(
            {
                "batch": batch,
                "program": program_labels.get(program, program),
                "registered": len(registered),
                "placed_on_campus": by_source.get("portal", 0),
                "placed_ppo": by_source.get("ppo", 0),
                "placed_off_campus": by_source.get("off_campus", 0),
                "placed_other_external": by_source.get("other", 0),
                "placed_total": len(placed),
                "placement_rate": metrics.rate(
                    len(placed), len(registered)
                ).as_dict(),
                "median_ctc_lpa": (
                    None if compensation is None else _text(compensation.median)
                ),
                "mean_ctc_lpa": (
                    None if compensation is None else _text(compensation.mean)
                ),
                "compensation_covered": (
                    0 if compensation is None else compensation.covered
                ),
                **{
                    tag: sum(
                        1
                        for enrollment_id in registered
                        if tags.get(enrollment_id) == tag
                    )
                    for tag in OUTCOME_TAGS
                },
                "registered_seeking": len(seeking),
                "placement_rate_seeking": metrics.rate(
                    len(placed), len(seeking)
                ).as_dict(),
            }
        )

    total_compensation = await metrics.compensation(
        executor, filters, outcome="placement"
    )
    total: dict[str, object] = {
        "batch": "All",
        "program": "All",
        "registered": computed.registered.count,
        "placed_on_campus": computed.placed.split["portal"],
        "placed_ppo": computed.placed.split["ppo"],
        "placed_off_campus": computed.placed.split["off_campus"],
        "placed_other_external": computed.placed.split["other"],
        "placed_total": computed.placed.count,
        "placement_rate": metrics.rate(
            computed.placed.count, computed.registered.count
        ).as_dict(),
        "median_ctc_lpa": _text(total_compensation.median),
        "mean_ctc_lpa": _text(total_compensation.mean),
        "compensation_covered": total_compensation.covered,
        **{
            tag: sum(1 for value in tags.values() if value == tag)
            for tag in OUTCOME_TAGS
        },
        "registered_seeking": computed.registered_seeking.count,
        "placement_rate_seeking": metrics.rate(
            computed.placed.count, computed.registered_seeking.count
        ).as_dict(),
    }

    return {
        "provisional": True,
        "note": PROVISIONAL_NOTE,
        "columns": [{"key": key, "label": label} for key, label in REPORT_COLUMNS],
        "rows": rows,
        "total": total,
    }


def _text(value: object) -> str | None:
    return None if value is None else str(value)


def report_rows_for_export(report: Mapping[str, object]) -> Sequence[Sequence[object]]:
    """The canned report as a header row plus body rows, for ANA-4.

    The export and the screen render the same object, so a spreadsheet handed
    to the office cannot carry different numbers from the page it was taken
    from -- which is the whole reason the report is assembled once.
    """
    columns = cast("list[dict[str, str]]", report["columns"])
    header = [column["label"] for column in columns]
    body: list[list[object]] = []
    for row in [*cast("list[dict[str, object]]", report["rows"]), report["total"]]:
        mapping = cast("dict[str, object]", row)
        body.append([_cell(mapping.get(column["key"])) for column in columns])
    return [header, *body]


def _cell(value: object) -> object:
    """A rate becomes its ratio; everything else prints as it stands."""
    if isinstance(value, dict) and "ratio" in value:
        return value["ratio"]
    return value
