"""Screen-shaped assembly over the ANA-1 metrics (LLD section 11.2).

Nothing here counts anything.  Every figure on every panel comes out of
``metrics.py``; this module's whole job is choosing which filters to ask with
and labelling what comes back.  That division is the reason a breakdown on the
cycle page cannot contradict the funnel above it: the breakdown is a partition
of the very cohorts the funnel reported, not a second query that ought to
agree.
"""

from __future__ import annotations

from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.modules.analytics import metrics
from app.modules.analytics.columns import (
    application_registry,
    membership_registry,
)
from app.modules.analytics.metrics import MetricFilters
from app.modules.analytics.reports import batch_report

#: gender_t, spelled out so an empty bucket still appears on the page.
GENDERS: tuple[tuple[str, str], ...] = (
    ("male", "Male"),
    ("female", "Female"),
    ("other", "Other"),
)


async def _labels(
    connection: AsyncConnection, table: str
) -> dict[str, str]:
    rows = (
        await connection.execute(sa.text(f"SELECT id, name FROM {table}"))
    ).mappings().all()
    return {str(cast(UUID, row["id"])): str(row["name"]) for row in rows}


async def _sectors(connection: AsyncConnection) -> list[tuple[UUID, str]]:
    rows = (
        await connection.execute(
            sa.text("SELECT id, name FROM sectors WHERE is_active ORDER BY name, id")
        )
    ).mappings().all()
    return [(cast(UUID, row["id"]), str(row["name"])) for row in rows]


async def _discipline_counts(
    connection: AsyncConnection, cycle_id: UUID
) -> dict[str, int]:
    """Strikes and penalties standing against this cycle's members.

    Scoped through membership rather than globally: the number a coordinator
    needs is how much discipline is live in the cycle they are running.
    """
    row = (
        await connection.execute(
            sa.text(
                """
                SELECT
                    (
                        SELECT count(*) FROM strikes s
                        JOIN cycle_memberships m ON m.enrollment_id = s.enrollment_id
                        WHERE m.cycle_id = :cycle_id AND s.is_active
                    ) AS active_strikes,
                    (
                        SELECT count(*) FROM penalties pe
                        JOIN cycle_memberships m ON m.enrollment_id = pe.enrollment_id
                        WHERE m.cycle_id = :cycle_id AND pe.is_active
                    ) AS active_penalties
                """
            ),
            {"cycle_id": cycle_id},
        )
    ).mappings().one()
    return {
        "active_strikes": int(row["active_strikes"]),
        "active_penalties": int(row["active_penalties"]),
    }


async def cycle_analytics(
    engine: AsyncEngine, cycle_id: UUID
) -> dict[str, object] | None:
    """ANA-2's cycle dashboard: funnel, compensation, breakdowns, panels."""
    async with engine.connect() as connection:
        cycle = (
            await connection.execute(
                sa.text(
                    "SELECT c.id, c.name, CAST(c.kind AS text) AS kind, c.starts_on, "
                    "c.archived_at FROM cycles c WHERE c.id = :id"
                ),
                {"id": cycle_id},
            )
        ).mappings().one_or_none()
        if cycle is None:
            return None

        filters = MetricFilters(cycle_ids=(cycle_id,))
        computed = await metrics.funnel(connection, filters)
        programs = await _labels(connection, "programs")
        branches = await _labels(connection, "branches")

        pending_approvals = int(
            await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM cycle_memberships "
                    "WHERE cycle_id = :id AND status = 'pending'"
                ),
                {"id": cycle_id},
            )
            or 0
        )

        body: dict[str, object] = {
            "cycle": {
                "id": str(cycle_id),
                "name": str(cycle["name"]),
                "kind": str(cycle["kind"]),
                "archived": cycle["archived_at"] is not None,
            },
            "funnel": computed.as_dict(),
            "compensation": await metrics.compensation_blocks(connection, filters),
            "breakdowns": {
                "program": await metrics.profile_breakdown(
                    connection, computed, column="p.program_id", labels=programs
                ),
                "branch": await metrics.profile_breakdown(
                    connection, computed, column="p.primary_branch_id", labels=branches
                ),
                "gender": await metrics.profile_breakdown(
                    connection, computed, column="p.gender", labels=dict(GENDERS)
                ),
                "sector": await metrics.sector_breakdown(
                    connection, filters, await _sectors(connection)
                ),
            },
            "top_companies": await metrics.top_companies(connection, filters),
            "timeline": await metrics.timeline(connection, filters),
            "discipline": await _discipline_counts(connection, cycle_id),
            "pending_approvals": pending_approvals,
            # the design review 4.22: a screen states every input its own controls
            # need. The export modal's column picker must offer exactly what
            # request_export accepts, so the registry travels with the screen
            # rather than being restated in the client.
            "export_columns": [
                {"key": column.key, "label": column.label, "family": column.family}
                for column in membership_registry()
            ],
        }
    return body


async def portal_analytics(engine: AsyncEngine) -> dict[str, object]:
    """ANA-2's portal dashboard: the same vocabulary, one row per year.

    Each year is its own scoped funnel over the cycles that started in it, so
    a yearly figure is the sum of the cycle figures a coordinator can open --
    never a separately-written aggregate that drifts from them.
    """
    async with engine.connect() as connection:
        cycles = (
            await connection.execute(
                sa.text(
                    "SELECT id, name, CAST(kind AS text) AS kind, starts_on "
                    "FROM cycles ORDER BY starts_on NULLS LAST, name"
                )
            )
        ).mappings().all()

        # SPEC-GAP (the design review 4.30i): ANA-2 asks for yearly trends and no cycle
        # carries an academic year.  Bucketed by starts_on's year; a cycle with
        # no start date groups under `undated` rather than being assigned a
        # year by inference from its name.
        by_year: dict[str, list[UUID]] = {}
        for row in cycles:
            starts_on = row["starts_on"]
            key = "undated" if starts_on is None else str(starts_on.year)
            by_year.setdefault(key, []).append(cast(UUID, row["id"]))

        years: list[dict[str, object]] = []
        for key in sorted(by_year, key=lambda value: (value == "undated", value)):
            filters = MetricFilters(cycle_ids=tuple(by_year[key]))
            computed = await metrics.funnel(connection, filters)
            years.append(
                {
                    "year": key,
                    "cycle_count": len(by_year[key]),
                    **computed.as_dict(),
                    "compensation": await metrics.compensation_blocks(
                        connection, filters
                    ),
                }
            )

        programs = await _labels(connection, "programs")
        all_cycles = MetricFilters(cycle_ids=tuple(cast(UUID, row["id"]) for row in cycles))
        overall = await metrics.funnel(connection, all_cycles)
        body: dict[str, object] = {
            "years": years,
            "overall": overall.as_dict(),
            "participation": [
                {
                    "cycle_id": str(cast(UUID, row["id"])),
                    "name": str(row["name"]),
                    "kind": str(row["kind"]),
                    "starts_on": (
                        None if row["starts_on"] is None else row["starts_on"].isoformat()
                    ),
                }
                for row in cycles
            ],
            # ANA-3's canned report rides on the portal page rather than a
            # screen of its own: it is the same cohorts this page already
            # counted, tabulated the way a filing wants them.
            "canned_report": await batch_report(
                connection, all_cycles, program_labels=programs
            ),
            "program_mix": await metrics.profile_breakdown(
                connection, overall, column="p.program_id", labels=programs
            ),
            "sector_mix": await metrics.sector_breakdown(
                connection, all_cycles, await _sectors(connection)
            ),
            # DER-1's dimensions, which is the one scope where an external
            # offer attached to nothing still counts as a placement.
            "portal_wide_placed": (
                await metrics.placed(connection, MetricFilters(outcome="placement"))
            ).as_dict(),
        }
    return body


async def job_analytics(engine: AsyncEngine, job_id: UUID) -> dict[str, object] | None:
    """ANA-2's job page: the pipeline for a full job, the funnel for an open one.

    Which shape a job gets is decided by its cycle's kind, exactly as JOB-1
    decides whether it has rounds at all: an open-cycle job records outcomes
    directly and has no per-round story to tell, so reporting empty round
    columns for it would invent a pipeline that does not exist.
    """
    async with engine.connect() as connection:
        job = (
            await connection.execute(
                sa.text(
                    "SELECT j.id, j.title, j.cycle_id, j.company_id, "
                    "CAST(j.outcome AS text) AS outcome, j.is_published, "
                    "j.cancelled_at, c.name AS company_name, "
                    "cy.name AS cycle_name, CAST(cy.kind AS text) AS cycle_kind "
                    "FROM jobs j JOIN companies c ON c.id = j.company_id "
                    "JOIN cycles cy ON cy.id = j.cycle_id WHERE j.id = :id"
                ),
                {"id": job_id},
            )
        ).mappings().one_or_none()
        if job is None:
            return None

        cycle_id = cast(UUID, job["cycle_id"])
        filters = MetricFilters(cycle_ids=(cycle_id,), job_id=job_id)
        is_pipeline = str(job["cycle_kind"]) != "open"

        applied = await metrics.applied(connection, filters)
        offered = await metrics.offered(connection, filters)
        placed = await metrics.placed(connection, filters)
        statuses = (
            await connection.execute(
                sa.text(
                    "SELECT CAST(status AS text) AS status, count(*) AS total "
                    "FROM applications WHERE job_id = :id GROUP BY status"
                ),
                {"id": job_id},
            )
        ).mappings().all()

        body: dict[str, object] = {
            "job": {
                "id": str(job_id),
                "title": str(job["title"]),
                "outcome": str(job["outcome"]),
                "published": bool(job["is_published"]),
                "cancelled": job["cancelled_at"] is not None,
                "company": {
                    "id": str(cast(UUID, job["company_id"])),
                    "name": str(job["company_name"]),
                },
                "cycle": {
                    "id": str(cycle_id),
                    "name": str(job["cycle_name"]),
                    "kind": str(job["cycle_kind"]),
                },
            },
            "shape": "pipeline" if is_pipeline else "open",
            # Both shapes share this line, because ANA-1 defines applied,
            # offered and accepted once regardless of how the job runs.
            "funnel": {
                "applied": applied.count,
                "offered": offered.count,
                "accepted": placed.count,
                "offer_conversion": metrics.rate(placed.count, offered.count).as_dict(),
            },
            "statuses": {
                str(row["status"]): int(row["total"]) for row in statuses
            },
            "compensation": await metrics.compensation_blocks(connection, filters),
            "rounds": (
                await metrics.round_funnel(connection, job_id) if is_pipeline else []
            ),
            # This job's own questions are part of its export registry, so the
            # picker cannot offer a column the command would refuse
            # (the design review 4.22).
            "export_columns": [
                {"key": column.key, "label": column.label, "family": column.family}
                for column in application_registry(
                    tuple(
                        (cast(UUID, row["id"]), str(row["text"]))
                        for row in (
                            await connection.execute(
                                sa.text(
                                    "SELECT id, text FROM job_questions "
                                    "WHERE job_id = :id ORDER BY ord"
                                ),
                                {"id": job_id},
                            )
                        ).mappings().all()
                    )
                )
            ],
        }
    return body


async def company_analytics(
    engine: AsyncEngine, company_id: UUID
) -> dict[str, object] | None:
    """ANA-2's cross-cycle company view, in the same vocabulary as everything else."""
    async with engine.connect() as connection:
        company = (
            await connection.execute(
                sa.text(
                    "SELECT c.id, c.name, c.is_active, s.name AS sector_name "
                    "FROM companies c LEFT JOIN sectors s ON s.id = c.sector_id "
                    "WHERE c.id = :id"
                ),
                {"id": company_id},
            )
        ).mappings().one_or_none()
        if company is None:
            return None

        filters = MetricFilters(company_id=company_id)
        applied = await metrics.applied(connection, filters)
        offered = await metrics.offered(connection, filters)
        placed = await metrics.placed(connection, filters)

        jobs = (
            await connection.execute(
                sa.text(
                    "SELECT j.id, j.title, CAST(j.outcome AS text) AS outcome, "
                    "j.is_published, j.cancelled_at, cy.id AS cycle_id, "
                    "cy.name AS cycle_name, cy.starts_on "
                    "FROM jobs j JOIN cycles cy ON cy.id = j.cycle_id "
                    "WHERE j.company_id = :id "
                    "ORDER BY cy.starts_on NULLS LAST, j.title"
                ),
                {"id": company_id},
            )
        ).mappings().all()
        programs = await _labels(connection, "programs")
        branches = await _labels(connection, "branches")
        offers = await metrics.offer_counts(connection, filters)
        hires_by_program = metrics.partition_counts(
            await metrics.dimension_of(connection, placed.ids, "p.program_id"),
            labels=programs,
        )
        hires_by_branch = metrics.partition_counts(
            await metrics.dimension_of(connection, placed.ids, "p.primary_branch_id"),
            labels=branches,
        )

        # Compensation history: one block per cycle this company hired into, so
        # a trajectory can be read without pooling years that are not
        # comparable.
        history: list[dict[str, object]] = []
        for cycle_id in sorted(
            {cast(UUID, row["cycle_id"]) for row in jobs},
            key=lambda value: str(value),
        ):
            scoped = MetricFilters(company_id=company_id, cycle_ids=(cycle_id,))
            cycle_name = next(
                str(row["cycle_name"])
                for row in jobs
                if cast(UUID, row["cycle_id"]) == cycle_id
            )
            history.append(
                {
                    "cycle_id": str(cycle_id),
                    "cycle_name": cycle_name,
                    "placed": (await metrics.placed(connection, scoped)).as_dict(),
                    "compensation": await metrics.compensation_blocks(
                        connection, scoped
                    ),
                }
            )

        body: dict[str, object] = {
            "company": {
                "id": str(company_id),
                "name": str(company["name"]),
                "is_active": bool(company["is_active"]),
                "sector": company["sector_name"],
            },
            "totals": {
                "jobs": len(jobs),
                "cancelled_jobs": sum(1 for row in jobs if row["cancelled_at"]),
                "applicants": applied.count,
                "offered": offered.count,
                "placed": placed.as_dict(),
                "offers_extended": offers["extended"],
                "offers_accepted": offers["accepted"],
                # the design review 4.30l: accepted over extended, counted in offer
                # rows rather than students, and labelled as such.
                "acceptance_rate": metrics.rate(
                    offers["accepted"], offers["extended"]
                ).as_dict(),
            },
            "jobs": [
                {
                    "id": str(cast(UUID, row["id"])),
                    "title": str(row["title"]),
                    "outcome": str(row["outcome"]),
                    "published": bool(row["is_published"]),
                    "cancelled": row["cancelled_at"] is not None,
                    "cycle_id": str(cast(UUID, row["cycle_id"])),
                    "cycle_name": str(row["cycle_name"]),
                }
                for row in jobs
            ],
            "hires_by_program": hires_by_program,
            "hires_by_branch": hires_by_branch,
            "compensation_history": history,
            "external_offers": await metrics.external_offer_mix(connection, filters),
        }
    return body
