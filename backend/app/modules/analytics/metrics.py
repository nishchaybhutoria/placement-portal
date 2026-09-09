"""ANA-1 -- the one vocabulary every dashboard, report, and export counts in.

Four counts and a rate, defined once.  Everything else in this milestone --
the cycle funnel, the portal trend, the job page, the company page, the canned
NIRF/RTI columns, the membership export -- is a projection of what is below,
because a report that disagrees with the system that produced it is worse than
no report: it is a number somebody defends in public a year later.

Three properties are load-bearing and are asserted by the M15 suites rather
than left to review:

* **No second definition of "accepted".**  Every offer fact comes from the SQL
  fragments in ``modules/offers/derivations.py`` -- the same ones the ELG-3
  gates gate on.  This module never names ``offers`` or ``external_offers``,
  and ``tests/analytics/test_no_parallel_sql.py`` fails the build if it ever
  does.  The gate and the dashboard cannot drift, because there is only one
  sentence for them to drift from.
* **Sets, not counts.**  Each metric returns the enrollment ids it counted, so
  a test can assert *which* students were counted and why, rather than that two
  totals happen to be equal -- two errors cancel in a total.  Screens project
  counts out of these; the ids do not leave the server.
* **Breakdowns are the same query with a GROUP BY.**  A per-program funnel that
  contradicts the cycle funnel above it is not possible here, because it is not
  computed by different code.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.modules.offers.derivations import (
    ACCEPTED_EXTERNAL_OFFERS_SQL,
    ACCEPTED_PORTAL_OFFERS_SQL,
    EXTENDED_PORTAL_OFFERS_SQL,
    OFFERED_EXTERNAL_OFFERS_SQL,
)

Executor = AsyncConnection | AsyncSession

#: The buckets ANA-1's on-portal/external split reports.  `other` is its own
#: bucket and is never folded into `off_campus`: external_source_t carries
#: three values where ANA-1's parenthetical names two, and an unclassified
#: acceptance quietly joining a named category is how a published figure grows
#: a number nobody can source.
# SPEC-GAP (the design review 4.30a): ANA-1 says "PPO/off-campus"; the enum also has
# `other`.  Reported separately rather than assigned to either.
PLACEMENT_SOURCES: tuple[str, ...] = ("portal", "ppo", "off_campus", "other")

#: Compensation lives in two incompatible units -- CTC in LPA, stipend in
#: rupees per month -- and an open cycle may hold both outcomes at once, so
#: there is no arithmetic that mixes them and no pooled "mean CTC" anywhere.
# SPEC-GAP (the design review 4.30c): ANA-1 asks for compensation stats without saying
# what happens to a cycle carrying both outcomes.  Always partitioned, never
# pooled; each block states its own unit.
COMPENSATION_UNITS: Mapping[str, str] = {
    "placement": "lpa",
    "internship": "inr_per_month",
}


@dataclass(frozen=True, slots=True)
class MetricFilters:
    """One filter object for every metric, so a breakdown cannot disagree.

    ``cycle_ids`` of ``None`` means portal-wide: DER-1's dimensions regardless
    of attachment, which is the only scope where an unattached external offer
    counts towards anything.
    """

    cycle_ids: tuple[UUID, ...] | None = None
    program_id: UUID | None = None
    branch_id: UUID | None = None
    gender: str | None = None
    graduating_year: int | None = None
    sector_id: UUID | None = None
    company_id: UUID | None = None
    job_id: UUID | None = None
    outcome: str | None = None
    #: ANA-3's honest denominator: active members carrying no outcome tag.
    seeking_only: bool = False

    def narrow(self, **changes: object) -> MetricFilters:
        """The same filters with one dimension pinned."""
        return replace(self, **changes)  # type: ignore[arg-type]


@dataclass(frozen=True, slots=True)
class Cohort:
    """A metric as the set of enrollments it counted."""

    ids: frozenset[UUID]

    @property
    def count(self) -> int:
        return len(self.ids)


@dataclass(frozen=True, slots=True)
class PlacedCohort:
    """Placed students, plus the source each one is attributed to.

    ``by_source`` partitions ``ids`` exactly -- a student placed by both a
    portal offer and an attached external inside one cycle appears once, under
    their most recent acceptance -- so the buckets always sum to ``count``.
    """

    ids: frozenset[UUID]
    by_source: Mapping[str, frozenset[UUID]]
    #: Acceptances not attributed to anyone because a more recent one won.
    discarded_acceptances: int

    @property
    def count(self) -> int:
        return len(self.ids)

    @property
    def split(self) -> dict[str, int]:
        """The four-way partition: every placed student in exactly one bucket."""
        return {
            source: len(self.by_source.get(source, frozenset()))
            for source in PLACEMENT_SOURCES
        }

    @property
    def channel_split(self) -> dict[str, int]:
        """ANA-1's headline split -- on-portal versus external -- summing to count."""
        counts = self.split
        return {
            "portal": counts["portal"],
            "external": sum(
                counts[source] for source in PLACEMENT_SOURCES if source != "portal"
            ),
        }

    @property
    def external_sources(self) -> dict[str, int]:
        """The external half broken out, summing to ``channel_split['external']``."""
        counts = self.split
        return {
            source: counts[source]
            for source in PLACEMENT_SOURCES
            if source != "portal"
        }

    def as_dict(self) -> dict[str, object]:
        """Two nested levels, each summing to the figure it sits under.

        ``split`` is ANA-1's sentence -- on-portal versus external -- and
        ``external_sources`` opens the external half into PPO, off-campus and
        other without ever letting a student appear in two buckets.
        """
        return {
            "total": self.count,
            "split": self.channel_split,
            "external_sources": self.external_sources,
            "discarded_acceptances": self.discarded_acceptances,
        }


@dataclass(frozen=True, slots=True)
class CompensationBlock:
    """Compensation over placed students, with the coverage that qualifies it.

    ``covered`` versus ``placed`` is not decoration.  A median drawn from three
    of forty placed students is a true number and a false impression, and the
    only defence is printing both beside it.
    """

    unit: str
    placed: int
    covered: int
    mean: Decimal | None
    median: Decimal | None
    minimum: Decimal | None
    maximum: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return {
            "unit": self.unit,
            "placed": self.placed,
            "covered": self.covered,
            "mean": _number(self.mean),
            "median": _number(self.median),
            "min": _number(self.minimum),
            "max": _number(self.maximum),
        }


@dataclass(frozen=True, slots=True)
class Rate:
    """A rate that ships its own arithmetic.

    The numerator and denominator travel with the ratio so that no consumer --
    a screen, an export, a spreadsheet somebody builds downstream -- has to
    recompute it and get a third answer.  ``None`` on an empty denominator: a
    placement rate over nobody is not zero.
    """

    numerator: int
    denominator: int
    ratio: Decimal | None

    def as_dict(self) -> dict[str, object]:
        return {
            "numerator": self.numerator,
            "denominator": self.denominator,
            "ratio": _number(self.ratio),
        }


def _number(value: Decimal | None) -> str | None:
    """Money and rates cross the wire as strings, never as binary floats."""
    return None if value is None else str(value)


def rate(numerator: int, denominator: int) -> Rate:
    """ANA-1's placement rate, and every rate shaped like it."""
    ratio = (
        (Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.0001"))
        if denominator
        else None
    )
    return Rate(numerator=numerator, denominator=denominator, ratio=ratio)


# --------------------------------------------------------------------------
# Row sources.  Built from the derivation fragments, never alongside them.
# --------------------------------------------------------------------------

_ACCEPTED_COLUMNS = (
    "enrollment_id, cycle_id, outcome, source, external_source, offer_id, "
    "application_id, job_id, company_id, accepted_at, ctc_lpa, stipend_month, "
    "snapshot_program_id"
)

_OFFERED_COLUMNS = (
    "enrollment_id, cycle_id, outcome, source, offer_id, job_id, company_id, extended_at"
)

_ACCEPTED_ROWS = f"""
    accepted_rows AS (
        SELECT {_ACCEPTED_COLUMNS} FROM ({ACCEPTED_PORTAL_OFFERS_SQL}) portal_accepted
        UNION ALL
        SELECT {_ACCEPTED_COLUMNS} FROM ({ACCEPTED_EXTERNAL_OFFERS_SQL}) ext_accepted
    )
"""

_OFFERED_ROWS = f"""
    offered_rows AS (
        SELECT {_OFFERED_COLUMNS} FROM ({EXTENDED_PORTAL_OFFERS_SQL}) portal_offered
        UNION ALL
        SELECT {_OFFERED_COLUMNS} FROM ({OFFERED_EXTERNAL_OFFERS_SQL}) ext_offered
    )
"""

#: The bucket an accepted or offered row belongs to in the ANA-1 split: the
#: portal, or the external source that recorded it.
_SPLIT_SOURCE = """
    CASE WHEN r.source = 'portal' THEN 'portal'
         ELSE COALESCE(CAST(r.external_source AS text), 'other')
    END
"""

#: Effective sector: the job's, else the company's, else unspecified.  An
#: external offer has no job and so always resolves through its company.
# SPEC-GAP (the design review 4.30p): ANA-2 names a sector breakdown; both
# jobs.sector_id and companies.sector_id exist and both are nullable.
_SECTOR_JOIN = """
    LEFT JOIN jobs sector_job ON sector_job.id = r.job_id
    LEFT JOIN companies sector_company ON sector_company.id = r.company_id
    """
_SECTOR_ID = "COALESCE(sector_job.sector_id, sector_company.sector_id)"


def _profile_predicate(filters: MetricFilters) -> tuple[str, dict[str, object]]:
    """The demographic filters, applied identically to every metric.

    Every caller joins ``profiles p`` under the alias this expects, so the
    per-program funnel and the cycle funnel are the same query twice.
    """
    clauses: list[str] = []
    params: dict[str, object] = {}
    if filters.program_id is not None:
        clauses.append("p.program_id = :program_id")
        params["program_id"] = filters.program_id
    if filters.branch_id is not None:
        clauses.append("p.primary_branch_id = :branch_id")
        params["branch_id"] = filters.branch_id
    if filters.gender is not None:
        clauses.append("CAST(p.gender AS text) = :gender")
        params["gender"] = filters.gender
    if filters.graduating_year is not None:
        clauses.append("p.graduating_year = :graduating_year")
        params["graduating_year"] = filters.graduating_year
    return (" AND ".join(clauses) if clauses else "TRUE"), params


def _cycle_predicate(filters: MetricFilters, column: str) -> tuple[str, dict[str, object]]:
    """Cycle scoping, or portal-wide when no cycles are named."""
    if filters.cycle_ids is None:
        return "TRUE", {}
    return f"{column} = ANY(:cycle_ids)", {"cycle_ids": list(filters.cycle_ids)}


def _outcome_predicate(filters: MetricFilters, column: str) -> tuple[str, dict[str, object]]:
    if filters.outcome is None:
        return "TRUE", {}
    return f"CAST({column} AS text) = :outcome", {"outcome": filters.outcome}


def _subject_predicate(
    filters: MetricFilters, *, company: str, job: str
) -> tuple[str, dict[str, object]]:
    """Narrow to one company or one job, wherever those columns live.

    The company page and the job page are the cycle page asked a narrower
    question, not a different question, which is why they take the same route
    through these predicates rather than growing queries of their own.
    """
    clauses: list[str] = []
    params: dict[str, object] = {}
    if filters.company_id is not None:
        clauses.append(f"{company} = :company_id")
        params["company_id"] = filters.company_id
    if filters.job_id is not None:
        clauses.append(f"{job} = :job_id")
        params["job_id"] = filters.job_id
    return (" AND ".join(clauses) if clauses else "TRUE"), params


async def _enrollment_ids(
    executor: Executor, sql: str, params: dict[str, object]
) -> frozenset[UUID]:
    rows = (await executor.execute(sa.text(sql), params)).scalars().all()
    return frozenset(cast(UUID, row) for row in rows)


# --------------------------------------------------------------------------
# ANA-1: registered, applied, offered, placed.
# --------------------------------------------------------------------------


async def registered(executor: Executor, filters: MetricFilters) -> Cohort:
    """ANA-1: *Registered* = ``active`` memberships.

    Auto-created memberships -- the ones an external-offer attachment writes
    for a student who never joined -- are `active` like any other and are
    counted here without a special case, which is exactly what EXT-3 intends:
    the student is in the cycle.

    ``seeking_only`` is ANA-3's alternative denominator.  All three
    ``outcome_tag_t`` values mean not seeking placement, so seeking is the
    absence of a tag.
    """
    profile_clause, params = _profile_predicate(filters)
    cycle_clause, cycle_params = _cycle_predicate(filters, "m.cycle_id")
    params.update(cycle_params)
    params["seeking_only"] = filters.seeking_only
    sql = f"""
        SELECT DISTINCT m.enrollment_id
        FROM cycle_memberships m
        LEFT JOIN profiles p ON p.enrollment_id = m.enrollment_id
        WHERE m.status = 'active'
          AND {cycle_clause}
          AND (NOT :seeking_only OR m.outcome_tag IS NULL)
          AND {profile_clause}
    """
    return Cohort(ids=await _enrollment_ids(executor, sql, params))


async def applied(executor: Executor, filters: MetricFilters) -> Cohort:
    """ANA-1: distinct enrollments with >=1 application **ever created**.

    No status filter, deliberately.  A withdrawn or auto-withdrawn application
    was still an application, and ANA-1 says "ever".  One consequence is worth
    stating rather than smoothing: because *registered* counts only memberships
    that are active *now*, a removed member who applied lifts applied without
    lifting registered, so applied may exceed registered.  That is faithful to
    the definitions and is surfaced as it stands.
    """
    profile_clause, params = _profile_predicate(filters)
    cycle_clause, cycle_params = _cycle_predicate(filters, "j.cycle_id")
    params.update(cycle_params)
    outcome_clause, outcome_params = _outcome_predicate(filters, "j.outcome")
    params.update(outcome_params)
    sector_clause = "TRUE"
    if filters.sector_id is not None:
        sector_clause = (
            "COALESCE(j.sector_id, applied_company.sector_id) = :sector_id"
        )
        params["sector_id"] = filters.sector_id
    subject_clause, subject_params = _subject_predicate(
        filters, company="j.company_id", job="j.id"
    )
    params.update(subject_params)
    sql = f"""
        SELECT DISTINCT a.enrollment_id
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        LEFT JOIN companies applied_company ON applied_company.id = j.company_id
        LEFT JOIN profiles p ON p.enrollment_id = a.enrollment_id
        WHERE {cycle_clause} AND {outcome_clause} AND {sector_clause}
          AND {subject_clause} AND {profile_clause}
    """
    return Cohort(ids=await _enrollment_ids(executor, sql, params))


async def offered(executor: Executor, filters: MetricFilters) -> Cohort:
    """ANA-1: >=1 Offer extended, or an attached external at status >= offered.

    Both halves count a since-declined offer: the student was offered.  See
    the design review 4.30h for why `declined` is on this side of the line.
    """
    profile_clause, params = _profile_predicate(filters)
    cycle_clause, cycle_params = _cycle_predicate(filters, "r.cycle_id")
    params.update(cycle_params)
    outcome_clause, outcome_params = _outcome_predicate(filters, "r.outcome")
    params.update(outcome_params)
    sector_clause = "TRUE"
    if filters.sector_id is not None:
        sector_clause = f"{_SECTOR_ID} = :sector_id"
        params["sector_id"] = filters.sector_id
    subject_clause, subject_params = _subject_predicate(
        filters, company="r.company_id", job="r.job_id"
    )
    params.update(subject_params)
    sql = f"""
        WITH {_OFFERED_ROWS}
        SELECT DISTINCT r.enrollment_id
        FROM offered_rows r
        {_SECTOR_JOIN}
        LEFT JOIN profiles p ON p.enrollment_id = r.enrollment_id
        WHERE {cycle_clause} AND {outcome_clause} AND {sector_clause}
          AND {subject_clause} AND {profile_clause}
    """
    return Cohort(ids=await _enrollment_ids(executor, sql, params))


_PLACED_SQL_TEMPLATE = """
    WITH {accepted_rows},
    scoped AS (
        SELECT r.enrollment_id, r.offer_id, r.accepted_at, {split_source} AS split_source
        FROM accepted_rows r
        {sector_join}
        LEFT JOIN profiles p ON p.enrollment_id = r.enrollment_id
        WHERE {cycle_clause} AND {outcome_clause} AND {sector_clause}
          AND {subject_clause} AND {profile_clause}
    ),
    attributed AS (
        SELECT DISTINCT ON (enrollment_id) enrollment_id, split_source
        FROM scoped
        ORDER BY enrollment_id, accepted_at DESC, offer_id DESC
    )
    SELECT
        attributed.enrollment_id,
        attributed.split_source,
        (SELECT count(*) FROM scoped) - (SELECT count(*) FROM attributed) AS discarded
    FROM attributed
"""


async def placed(executor: Executor, filters: MetricFilters) -> PlacedCohort:
    """ANA-1: >=1 accepted, non-terminated offer in scope, split by source.

    Scope is the cycle's own jobs *or* an external offer attached to it -- the
    external fragment aliases ``attached_cycle_id`` as its cycle, so both
    halves of ANA-1's sentence are one predicate.  Portal-wide (``cycle_ids``
    is None) drops the predicate entirely, which is the only scope where an
    unattached external acceptance counts.

    A student with several acceptances is attributed to the most recent one --
    not the largest, which would bias every published figure in the single
    direction that flatters the institute (the design review 4.30e).  That attribution
    is what makes the split a partition rather than two overlapping counts.
    """
    profile_clause, params = _profile_predicate(filters)
    cycle_clause, cycle_params = _cycle_predicate(filters, "r.cycle_id")
    params.update(cycle_params)
    outcome_clause, outcome_params = _outcome_predicate(filters, "r.outcome")
    params.update(outcome_params)
    sector_clause = "TRUE"
    if filters.sector_id is not None:
        sector_clause = f"{_SECTOR_ID} = :sector_id"
        params["sector_id"] = filters.sector_id
    subject_clause, subject_params = _subject_predicate(
        filters, company="r.company_id", job="r.job_id"
    )
    params.update(subject_params)
    sql = _PLACED_SQL_TEMPLATE.format(
        accepted_rows=_ACCEPTED_ROWS,
        split_source=_SPLIT_SOURCE,
        sector_join=_SECTOR_JOIN,
        cycle_clause=cycle_clause,
        outcome_clause=outcome_clause,
        sector_clause=sector_clause,
        subject_clause=subject_clause,
        profile_clause=profile_clause,
    )
    rows = (await executor.execute(sa.text(sql), params)).mappings().all()
    buckets: dict[str, set[UUID]] = {source: set() for source in PLACEMENT_SOURCES}
    ids: set[UUID] = set()
    discarded = 0
    for row in rows:
        enrollment_id = cast(UUID, row["enrollment_id"])
        ids.add(enrollment_id)
        buckets.setdefault(str(row["split_source"]), set()).add(enrollment_id)
        discarded = int(row["discarded"])
    return PlacedCohort(
        ids=frozenset(ids),
        by_source={source: frozenset(members) for source, members in buckets.items()},
        discarded_acceptances=discarded,
    )


# --------------------------------------------------------------------------
# ANA-1: compensation.
# --------------------------------------------------------------------------

_COMPENSATION_SQL_TEMPLATE = """
    WITH {accepted_rows},
    scoped AS (
        SELECT
            r.enrollment_id, r.offer_id, r.accepted_at, r.job_id,
            r.snapshot_program_id, r.ctc_lpa, r.stipend_month
        FROM accepted_rows r
        {sector_join}
        LEFT JOIN profiles p ON p.enrollment_id = r.enrollment_id
        WHERE CAST(r.outcome AS text) = :comp_outcome
          AND {cycle_clause} AND {sector_clause} AND {subject_clause}
          AND {profile_clause}
    ),
    attributed AS (
        SELECT DISTINCT ON (enrollment_id) *
        FROM scoped
        ORDER BY enrollment_id, accepted_at DESC, offer_id DESC
    ),
    resolved AS (
        SELECT
            attributed.enrollment_id,
            -- ANA-1: the per-program CTC row when defined, else the job CTC.
            -- The program is the application's snapshot, so a later profile
            -- correction cannot move a published mean (the design review 4.30d), and
            -- an external offer -- which has no snapshot -- misses this join
            -- by construction and keeps its own recorded compensation.
            CASE WHEN :comp_outcome = 'placement'
                 THEN COALESCE(program_ctc.ctc_lpa, attributed.ctc_lpa)
                 ELSE attributed.stipend_month
            END AS amount
        FROM attributed
        LEFT JOIN job_program_ctc program_ctc
               ON program_ctc.job_id = attributed.job_id
              AND program_ctc.program_id = attributed.snapshot_program_id
    )
    SELECT
        (SELECT count(*) FROM attributed) AS placed,
        (SELECT count(*) FROM scoped) - (SELECT count(*) FROM attributed) AS discarded,
        count(amount) AS covered,
        avg(amount) AS mean,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY amount) AS median,
        min(amount) AS minimum,
        max(amount) AS maximum
    FROM resolved
"""


async def compensation(
    executor: Executor, filters: MetricFilters, *, outcome: str
) -> CompensationBlock:
    """ANA-1 compensation stats for one outcome, median via ``percentile_cont``.

    Rows without a recorded amount are excluded from every statistic and are
    visible in the gap between ``placed`` and ``covered``.  Nothing here mixes
    LPA with a monthly stipend; the caller asks for one outcome at a time
    because there is no meaningful answer that spans both.
    """
    if outcome not in COMPENSATION_UNITS:
        raise ValueError(f"Compensation is defined per outcome, not for {outcome!r}")
    profile_clause, params = _profile_predicate(filters)
    cycle_clause, cycle_params = _cycle_predicate(filters, "r.cycle_id")
    params.update(cycle_params)
    sector_clause = "TRUE"
    if filters.sector_id is not None:
        sector_clause = f"{_SECTOR_ID} = :sector_id"
        params["sector_id"] = filters.sector_id
    params["comp_outcome"] = outcome
    subject_clause, subject_params = _subject_predicate(
        filters, company="r.company_id", job="r.job_id"
    )
    params.update(subject_params)
    sql = _COMPENSATION_SQL_TEMPLATE.format(
        accepted_rows=_ACCEPTED_ROWS,
        sector_join=_SECTOR_JOIN,
        cycle_clause=cycle_clause,
        sector_clause=sector_clause,
        subject_clause=subject_clause,
        profile_clause=profile_clause,
    )
    row = (await executor.execute(sa.text(sql), params)).mappings().one()
    return CompensationBlock(
        unit=COMPENSATION_UNITS[outcome],
        placed=int(row["placed"]),
        covered=int(row["covered"]),
        mean=_decimal(row["mean"]),
        median=_decimal(row["median"]),
        minimum=_decimal(row["minimum"]),
        maximum=_decimal(row["maximum"]),
    )


def _decimal(value: object) -> Decimal | None:
    """Money stays decimal all the way out; averages round to two places."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.01"))


async def compensation_blocks(
    executor: Executor, filters: MetricFilters
) -> dict[str, dict[str, object]]:
    """Both outcome blocks, each labelled with its own unit."""
    return {
        outcome: (await compensation(executor, filters, outcome=outcome)).as_dict()
        for outcome in COMPENSATION_UNITS
    }


# --------------------------------------------------------------------------
# The funnel every surface renders.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Funnel:
    """ANA-1's four counts, the split, and both ANA-3 denominators."""

    registered: Cohort
    registered_seeking: Cohort
    applied: Cohort
    offered: Cohort
    placed: PlacedCohort

    def as_dict(self) -> dict[str, object]:
        return {
            "registered": self.registered.count,
            # ANA-3 asks for honest denominators but gives no formula, so both
            # are reported and both are labelled.  The unqualified rate is
            # always ANA-1's (the design review 4.30b).
            "registered_seeking": self.registered_seeking.count,
            "applied": self.applied.count,
            "offered": self.offered.count,
            "placed": self.placed.as_dict(),
            "placement_rate": rate(
                self.placed.count, self.registered.count
            ).as_dict(),
            "placement_rate_seeking": rate(
                self.placed.count, self.registered_seeking.count
            ).as_dict(),
        }


async def funnel(executor: Executor, filters: MetricFilters) -> Funnel:
    """registered -> applied -> offered -> placed, in one vocabulary."""
    return Funnel(
        registered=await registered(executor, filters),
        registered_seeking=await registered(
            executor, filters.narrow(seeking_only=True)
        ),
        applied=await applied(executor, filters),
        offered=await offered(executor, filters),
        placed=await placed(executor, filters),
    )


async def _profile_dimension(
    executor: Executor, enrollment_ids: frozenset[UUID], column: str
) -> dict[UUID, str | None]:
    """What each enrollment's profile says for one breakdown dimension."""
    if not enrollment_ids:
        return {}
    rows = (
        await executor.execute(
            sa.text(
                # Aliased `p` because callers name their column the way
                # _profile_predicate does; an unaliased FROM here is the M9
                # failure exactly, and the screen ratchet caught it.
                f"SELECT p.enrollment_id, CAST({column} AS text) AS value "
                "FROM profiles p WHERE p.enrollment_id = ANY(:ids)"
            ),
            {"ids": list(enrollment_ids)},
        )
    ).mappings().all()
    found = {
        cast(UUID, row["enrollment_id"]): (
            None if row["value"] is None else str(row["value"])
        )
        for row in rows
    }
    # An enrollment with no profile row at all is not dropped; it lands in the
    # same unknown bucket as one whose field is empty, because a breakdown that
    # loses people is worse than one that admits it does not know.
    return {enrollment_id: found.get(enrollment_id) for enrollment_id in enrollment_ids}


#: The bucket a row with no value for the dimension falls into.  It is always
#: reported, never filtered away, so the parts sum to the whole.
UNKNOWN_BUCKET = "unknown"


def _partition(
    cohort_ids: frozenset[UUID], dimension: Mapping[UUID, str | None]
) -> dict[str, frozenset[UUID]]:
    buckets: dict[str, set[UUID]] = {}
    for enrollment_id in cohort_ids:
        key = dimension.get(enrollment_id) or UNKNOWN_BUCKET
        buckets.setdefault(key, set()).add(enrollment_id)
    return {key: frozenset(members) for key, members in buckets.items()}


async def profile_breakdown(
    executor: Executor,
    computed: Funnel,
    *,
    column: str,
    labels: Mapping[str, str],
) -> list[dict[str, object]]:
    """One row per value of a profile dimension, partitioning a single funnel.

    This does not re-run the metrics per bucket.  Every cohort is computed once
    at the cycle level and then *partitioned*, so a per-program funnel is a
    subdivision of the funnel printed above it and cannot contradict it -- the
    parts sum to the whole because they are the whole, split up.  (A sector
    breakdown cannot work this way: sector is a property of the job, not of the
    student, so it keeps its own scoped queries below.)
    """
    everyone = (
        computed.registered.ids
        | computed.applied.ids
        | computed.offered.ids
        | computed.placed.ids
    )
    dimension = await _profile_dimension(executor, everyone, column)
    registered_parts = _partition(computed.registered.ids, dimension)
    seeking_parts = _partition(computed.registered_seeking.ids, dimension)
    applied_parts = _partition(computed.applied.ids, dimension)
    offered_parts = _partition(computed.offered.ids, dimension)
    placed_parts = _partition(computed.placed.ids, dimension)
    source_parts = {
        source: _partition(members, dimension)
        for source, members in computed.placed.by_source.items()
    }

    keys = sorted(
        set(registered_parts)
        | set(applied_parts)
        | set(offered_parts)
        | set(placed_parts)
        | set(labels)
    )
    rows: list[dict[str, object]] = []
    for key in keys:
        registered_count = len(registered_parts.get(key, frozenset()))
        seeking_count = len(seeking_parts.get(key, frozenset()))
        placed_count = len(placed_parts.get(key, frozenset()))
        rows.append(
            {
                "key": key,
                "label": labels.get(key, UNKNOWN_BUCKET if key == UNKNOWN_BUCKET else key),
                "registered": registered_count,
                "registered_seeking": seeking_count,
                "applied": len(applied_parts.get(key, frozenset())),
                "offered": len(offered_parts.get(key, frozenset())),
                "placed": placed_count,
                "placed_split": {
                    source: len(source_parts.get(source, {}).get(key, frozenset()))
                    for source in PLACEMENT_SOURCES
                },
                "placement_rate": rate(placed_count, registered_count).as_dict(),
                "placement_rate_seeking": rate(placed_count, seeking_count).as_dict(),
            }
        )
    return rows


async def sector_breakdown(
    executor: Executor, filters: MetricFilters, sectors: Sequence[tuple[UUID, str]]
) -> list[dict[str, object]]:
    """Applied/offered/placed per sector -- and deliberately no rate.

    Sector belongs to the job, not to the student, so there is no such thing as
    "registered in a sector" and therefore no honest denominator to divide by.
    Printing a rate here would mean inventing one.
    """
    rows: list[dict[str, object]] = []
    for sector_id, label in sectors:
        scoped = filters.narrow(sector_id=sector_id)
        scoped_placed = await placed(executor, scoped)
        rows.append(
            {
                "key": str(sector_id),
                "label": label,
                "applied": (await applied(executor, scoped)).count,
                "offered": (await offered(executor, scoped)).count,
                "placed": scoped_placed.count,
                "placed_split": scoped_placed.split,
            }
        )
    return rows


# --------------------------------------------------------------------------
# Panels that group the same attributed rows a different way.
# --------------------------------------------------------------------------

_TOP_COMPANIES_SQL_TEMPLATE = """
    WITH {accepted_rows},
    scoped AS (
        SELECT r.enrollment_id, r.offer_id, r.accepted_at, r.company_id
        FROM accepted_rows r
        LEFT JOIN profiles p ON p.enrollment_id = r.enrollment_id
        WHERE {cycle_clause} AND {outcome_clause} AND {subject_clause}
          AND {profile_clause}
    ),
    attributed AS (
        SELECT DISTINCT ON (enrollment_id) enrollment_id, company_id
        FROM scoped
        ORDER BY enrollment_id, accepted_at DESC, offer_id DESC
    )
    SELECT
        attributed.company_id,
        companies.name AS company_name,
        count(*) AS placed
    FROM attributed
    JOIN companies ON companies.id = attributed.company_id
    GROUP BY attributed.company_id, companies.name
    ORDER BY placed DESC, companies.name
    LIMIT :limit
"""


async def top_companies(
    executor: Executor, filters: MetricFilters, *, limit: int = 10
) -> list[dict[str, object]]:
    """Companies ranked by placed students (the design review 4.30q).

    Grouped over the *attributed* acceptances -- the same one-per-student rows
    the headline figure counts -- so the column sums to the cycle's placed
    total instead of to the number of offers that happened to be accepted.
    """
    profile_clause, params = _profile_predicate(filters)
    cycle_clause, cycle_params = _cycle_predicate(filters, "r.cycle_id")
    params.update(cycle_params)
    outcome_clause, outcome_params = _outcome_predicate(filters, "r.outcome")
    params.update(outcome_params)
    params["limit"] = limit
    subject_clause, subject_params = _subject_predicate(
        filters, company="r.company_id", job="r.job_id"
    )
    params.update(subject_params)
    sql = _TOP_COMPANIES_SQL_TEMPLATE.format(
        accepted_rows=_ACCEPTED_ROWS,
        cycle_clause=cycle_clause,
        outcome_clause=outcome_clause,
        subject_clause=subject_clause,
        profile_clause=profile_clause,
    )
    rows = (await executor.execute(sa.text(sql), params)).mappings().all()
    return [
        {
            "company_id": str(cast(UUID, row["company_id"])),
            "name": str(row["company_name"]),
            "placed": int(row["placed"]),
        }
        for row in rows
    ]


_TIMELINE_SQL_TEMPLATE = """
    WITH {accepted_rows}, {offered_rows},
    applications_by_day AS (
        SELECT date_trunc('day', a.applied_at) AS day, count(*) AS total
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        WHERE {applications_cycle_clause}
        GROUP BY 1
    ),
    offers_by_day AS (
        SELECT date_trunc('day', r.extended_at) AS day, count(*) AS total
        FROM offered_rows r
        WHERE {offered_cycle_clause}
        GROUP BY 1
    ),
    acceptances_by_day AS (
        SELECT date_trunc('day', r.accepted_at) AS day, count(*) AS total
        FROM accepted_rows r
        WHERE {accepted_cycle_clause}
        GROUP BY 1
    )
    SELECT
        day,
        sum(applications) AS applications,
        sum(offers) AS offers,
        sum(acceptances) AS acceptances
    FROM (
        SELECT day, total AS applications, 0 AS offers, 0 AS acceptances
        FROM applications_by_day
        UNION ALL
        SELECT day, 0, total, 0 FROM offers_by_day
        UNION ALL
        SELECT day, 0, 0, total FROM acceptances_by_day
    ) merged
    WHERE day IS NOT NULL
    GROUP BY day
    ORDER BY day
"""


async def timeline(executor: Executor, filters: MetricFilters) -> list[dict[str, object]]:
    """Applications, offers, and acceptances per day, on one axis.

    Three series counted exactly as the funnel counts them, so the shape of the
    chart and the totals printed above it come from one definition rather than
    from a query written to make a chart look right.
    """
    params: dict[str, object] = {}
    applications_clause, application_params = _cycle_predicate(filters, "j.cycle_id")
    params.update(application_params)
    offered_clause, _ = _cycle_predicate(filters, "r.cycle_id")
    accepted_clause, _ = _cycle_predicate(filters, "r.cycle_id")
    sql = _TIMELINE_SQL_TEMPLATE.format(
        accepted_rows=_ACCEPTED_ROWS,
        offered_rows=_OFFERED_ROWS,
        applications_cycle_clause=applications_clause,
        offered_cycle_clause=offered_clause,
        accepted_cycle_clause=accepted_clause,
    )
    rows = (await executor.execute(sa.text(sql), params)).mappings().all()
    return [
        {
            "day": _day(row["day"]),
            "applications": int(row["applications"]),
            "offers": int(row["offers"]),
            "acceptances": int(row["acceptances"]),
        }
        for row in rows
    ]


def _day(value: object) -> str:
    """A timestamptz bucket as the date string a chart axis reads."""
    return cast(datetime, value).date().isoformat()


# --------------------------------------------------------------------------
# ANA-2: the per-round pipeline.
# --------------------------------------------------------------------------

#: Round entry is the event that set `current_round_id` to that round -- the
#: `created` event for round one, an `advanced` event thereafter -- and exit is
#: the next event on that application.  Rows still sitting in the round are
#: excluded rather than measured to now(), which would make the median drift
#: every time somebody refreshed the page.
# SPEC-GAP (the design review 4.30j): ANA-2 asks for time-in-round without saying which
# instants bound it, or what to do with an application that has not left.
_TIME_IN_ROUND_SQL = """
    WITH entries AS (
        SELECT
            ev.application_id,
            ev.to_round_id AS round_id,
            ev.created_at AS entered_at,
            ev.event_seq AS entered_seq
        FROM application_events ev
        JOIN applications a ON a.id = ev.application_id
        WHERE ev.to_round_id IS NOT NULL AND a.job_id = :job_id
    ),
    passages AS (
        SELECT
            entries.round_id,
            entries.entered_at,
            (
                SELECT nxt.created_at
                FROM application_events nxt
                WHERE nxt.application_id = entries.application_id
                  AND nxt.event_seq > entries.entered_seq
                ORDER BY nxt.event_seq
                LIMIT 1
            ) AS exited_at
        FROM entries
    )
    SELECT
        round_id,
        count(*) AS closed_passages,
        avg(exited_at - entered_at) AS mean_interval,
        percentile_cont(0.5) WITHIN GROUP (
            ORDER BY EXTRACT(EPOCH FROM (exited_at - entered_at))
        ) AS median_seconds
    FROM passages
    WHERE exited_at IS NOT NULL
    GROUP BY round_id
"""

_ROUND_FUNNEL_SQL = """
    SELECT
        jr.id AS round_id,
        jr.name,
        jr.ord,
        count(rs.id) AS entered,
        count(*) FILTER (WHERE rs.result = 'advanced') AS advanced,
        count(*) FILTER (WHERE rs.result = 'eliminated') AS eliminated,
        count(*) FILTER (WHERE rs.result = 'waitlisted') AS waitlisted,
        count(*) FILTER (WHERE rs.result = 'pending') AS pending,
        count(*) FILTER (WHERE rs.attendance = 'absent') AS absent,
        count(*) FILTER (WHERE rs.attendance = 'excused') AS excused,
        count(*) FILTER (WHERE rs.attendance = 'present') AS present
    FROM job_rounds jr
    LEFT JOIN application_round_states rs ON rs.round_id = jr.id
    WHERE jr.job_id = :job_id
    GROUP BY jr.id, jr.name, jr.ord
    ORDER BY jr.ord
"""


async def round_funnel(executor: Executor, job_id: UUID) -> list[dict[str, object]]:
    """Per-round entered/advanced/eliminated/absent/waitlisted, with conversion.

    `excused` is its own count and is never folded into `absent`: RND-3 gives
    them different consequences -- one draws a strike where policy says so, the
    other never does -- so merging them would misreport the very thing the
    round page exists to show (the design review 4.30k).
    """
    rows = (
        await executor.execute(sa.text(_ROUND_FUNNEL_SQL), {"job_id": job_id})
    ).mappings().all()
    timings = {
        cast(UUID, row["round_id"]): row
        for row in (
            await executor.execute(sa.text(_TIME_IN_ROUND_SQL), {"job_id": job_id})
        ).mappings().all()
    }
    funnel_rows: list[dict[str, object]] = []
    for row in rows:
        round_id = cast(UUID, row["round_id"])
        entered = int(row["entered"])
        advanced = int(row["advanced"])
        timing = timings.get(round_id)
        median_seconds = None if timing is None else timing["median_seconds"]
        funnel_rows.append(
            {
                "round_id": str(round_id),
                "name": str(row["name"]),
                "ord": int(row["ord"]),
                "entered": entered,
                "advanced": advanced,
                "eliminated": int(row["eliminated"]),
                "waitlisted": int(row["waitlisted"]),
                "pending": int(row["pending"]),
                "absent": int(row["absent"]),
                "excused": int(row["excused"]),
                "present": int(row["present"]),
                "conversion": rate(advanced, entered).as_dict(),
                "closed_passages": 0 if timing is None else int(timing["closed_passages"]),
                "median_hours": (
                    None
                    if median_seconds is None
                    else str(
                        (Decimal(str(median_seconds)) / Decimal(3600)).quantize(
                            Decimal("0.01")
                        )
                    )
                ),
            }
        )
    return funnel_rows


async def dimension_of(
    executor: Executor, enrollment_ids: frozenset[UUID], column: str
) -> dict[UUID, str | None]:
    """Public form of the breakdown lookup, for panels that group one cohort."""
    return await _profile_dimension(executor, enrollment_ids, column)


def partition_counts(
    dimension: Mapping[UUID, str | None], *, labels: Mapping[str, str]
) -> list[dict[str, object]]:
    """Count a cohort by one dimension, unknowns included and named."""
    buckets = _partition(frozenset(dimension), dimension)
    return [
        {
            "key": key,
            "label": labels.get(key, UNKNOWN_BUCKET if key == UNKNOWN_BUCKET else key),
            "count": len(members),
        }
        for key, members in sorted(buckets.items())
    ]


_OFFER_COUNTS_SQL_TEMPLATE = """
    WITH {offered_rows}, {accepted_rows}
    SELECT
        (
            SELECT count(*) FROM offered_rows r
            WHERE {offered_cycle_clause} AND {offered_subject_clause}
        ) AS extended,
        (
            SELECT count(*) FROM accepted_rows r
            WHERE {accepted_cycle_clause} AND {accepted_subject_clause}
        ) AS accepted
"""


async def offer_counts(executor: Executor, filters: MetricFilters) -> dict[str, int]:
    """Offer rows extended and accepted -- rows, not students.

    ANA-2's company acceptance rate is `accepted / extended`, and a per-student
    reading of the same words gives a different number for any company that
    extended two offers to one person (the design review 4.30l).  Counting rows here
    keeps the rate saying what its label says.
    """
    params: dict[str, object] = {}
    cycle_clause, cycle_params = _cycle_predicate(filters, "r.cycle_id")
    params.update(cycle_params)
    subject_clause, subject_params = _subject_predicate(
        filters, company="r.company_id", job="r.job_id"
    )
    params.update(subject_params)
    sql = _OFFER_COUNTS_SQL_TEMPLATE.format(
        offered_rows=_OFFERED_ROWS,
        accepted_rows=_ACCEPTED_ROWS,
        offered_cycle_clause=cycle_clause,
        offered_subject_clause=subject_clause,
        accepted_cycle_clause=cycle_clause,
        accepted_subject_clause=subject_clause,
    )
    row = (await executor.execute(sa.text(sql), params)).mappings().one()
    return {"extended": int(row["extended"]), "accepted": int(row["accepted"])}


_EXTERNAL_MIX_SQL = f"""
    SELECT
        CAST(ext.status AS text) AS status,
        CAST(ext.external_source AS text) AS source,
        count(*) AS total
    FROM ({OFFERED_EXTERNAL_OFFERS_SQL}) ext
    WHERE (CAST(:company_id AS uuid) IS NULL OR ext.company_id = CAST(:company_id AS uuid))
    GROUP BY 1, 2
    ORDER BY 1, 2
"""


async def external_offer_mix(
    executor: Executor, filters: MetricFilters
) -> list[dict[str, object]]:
    """External offers by status and source, through the derivation fragment.

    The fragment already spans every value of external_status_t, so this is the
    whole population and not a second opinion about which rows exist.
    """
    rows = (
        await executor.execute(
            sa.text(_EXTERNAL_MIX_SQL), {"company_id": filters.company_id}
        )
    ).mappings().all()
    return [
        {
            "status": str(row["status"]),
            "source": str(row["source"]),
            "total": int(row["total"]),
        }
        for row in rows
    ]
