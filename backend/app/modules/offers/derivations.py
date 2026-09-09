"""Live offer-derived facts used by eligibility and offer acceptance.

Behavior DER-1 deliberately stores no placed flag or cap counter.  The source of
truth is the accepted offer rows themselves, so every caller asks these queries
inside its existing transaction and passes the resulting booleans/counts into a
pure decision.  The two accepted-source fragments below are the single SQL
vocabulary for portal and external acceptances; screens, commands, and later
analytics must not grow subtly different definitions of "accepted".

M15 made that last sentence structural.  ``modules/analytics`` is forbidden by a
source-level ratchet from naming ``offers`` or ``external_offers`` at all, so
every fact ANA-1 counts has to be expressible here: the two accepted fragments
gained the identity and compensation columns analytics needs, and the two
"offered" fragments below were added because *offered* is a wider set than
*accepted* and could not be carved out of them.  This module is now the only
place in the system that turns an offer table into a fact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

Executor = AsyncConnection | AsyncSession

#: ANA-4 needs both an "ever issued" cohort predicate and display details.
#: Keeping these fragments here preserves this module as the only SQL vocabulary
#: that turns portal offer rows into facts.
JOB_APPLICATION_HAS_OFFER_SQL = (
    "EXISTS (SELECT 1 FROM offers issued WHERE issued.application_id = a.id)"
)
JOB_APPLICATION_OFFER_EXPORT_LATERAL_SQL = """
    SELECT count(*) AS offer_count,
           string_agg(
             CASE WHEN issued.terminated_at IS NOT NULL THEN 'terminated'
                  WHEN issued.response IS NOT NULL THEN CAST(issued.response AS text)
                  ELSE 'pending' END,
             ', ' ORDER BY issued.extended_at
           ) AS offer_statuses,
           (array_agg(issued.extended_at ORDER BY issued.extended_at DESC))[1]
             AS extended_at,
           (array_agg(issued.deadline_at ORDER BY issued.extended_at DESC))[1]
             AS deadline_at,
           (array_agg(issued.responded_at ORDER BY issued.extended_at DESC))[1]
             AS responded_at,
           (array_agg(issued.termination_reason ORDER BY issued.extended_at DESC))[1]
             AS termination_reason
    FROM offers issued WHERE issued.application_id = a.id
"""

#: Portal offers count only while accepted and unterminated.  Application
#: status is intentionally absent: DER-1 is defined from the offer source row,
#: and M12 commands keep the denormalized application status in the same plan.
ACCEPTED_PORTAL_OFFERS_SQL = """
    SELECT
        a.enrollment_id,
        j.cycle_id,
        j.outcome,
        CAST('portal' AS text) AS source,
        CAST(NULL AS external_source_t) AS external_source,
        o.id AS offer_id,
        a.id AS application_id,
        j.id AS job_id,
        j.company_id,
        COALESCE(o.responded_at, o.extended_at) AS accepted_at,
        j.ctc_lpa,
        j.stipend_month,
        -- ANA-1 resolves a per-program CTC against the program the eligibility
        -- decision actually saw (the design review 4.30d), which is the snapshot, not
        -- the live profile.  A snapshot predating the field, or holding
        -- anything that is not a UUID, yields NULL and so falls back to the
        -- job CTC: a malformed snapshot must not fail a dashboard.
        CASE
            WHEN a.profile_snapshot ->> 'program_id'
                 ~ '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
            THEN CAST(a.profile_snapshot ->> 'program_id' AS uuid)
        END AS snapshot_program_id
    FROM offers o
    JOIN applications a ON a.id = o.application_id
    JOIN jobs j ON j.id = a.job_id
    WHERE o.response = 'accepted' AND o.terminated_at IS NULL
"""

#: External offers have no termination columns.  They count globally as soon
#: as accepted; cycle-local internship/cap facts use attached_cycle_id, while
#: an unattached placement acceptance still contributes to DER-1 globally.
ACCEPTED_EXTERNAL_OFFERS_SQL = """
    SELECT
        eo.enrollment_id,
        eo.attached_cycle_id AS cycle_id,
        eo.outcome,
        CAST('external' AS text) AS source,
        eo.source AS external_source,
        eo.id AS offer_id,
        CAST(NULL AS uuid) AS application_id,
        CAST(NULL AS uuid) AS job_id,
        eo.company_id,
        COALESCE(CAST(eo.responded_on AS timestamptz), eo.created_at) AS accepted_at,
        eo.ctc_lpa,
        eo.stipend_month,
        -- An external offer has no application and so no snapshot; ANA-1 says
        -- it carries its own recorded compensation, and job_program_ctc never
        -- applies to it.  NULL here makes that join miss by construction.
        CAST(NULL AS uuid) AS snapshot_program_id
    FROM external_offers eo
    WHERE eo.status = 'accepted'
"""

#: ANA-1 counts a student as *offered* on the strength of an offer having been
#: extended at all -- ">=1 Offer extended", ever.  A since-declined, terminated,
#: or expired offer still happened, so nothing here filters on response or
#: termination (the design review 4.30h).  Offered is a reach statistic, not a standing
#: one; the standing question is what ACCEPTED_PORTAL_OFFERS_SQL answers.
EXTENDED_PORTAL_OFFERS_SQL = """
    SELECT
        a.enrollment_id,
        j.cycle_id,
        j.outcome,
        CAST('portal' AS text) AS source,
        CAST(NULL AS external_source_t) AS external_source,
        o.id AS offer_id,
        a.id AS application_id,
        j.id AS job_id,
        j.company_id,
        o.extended_at,
        o.response,
        o.terminated_at
    FROM offers o
    JOIN applications a ON a.id = o.application_id
    JOIN jobs j ON j.id = a.job_id
"""

#: ANA-1 says "attached external offer in status >= offered", but
#: external_status_t is offered|accepted|declined and `declined` sits on no
#: ordinal ladder.  A student who declined was nonetheless offered, which is
#: also how the portal half of the same sentence reads, so all three statuses
#: count (the design review 4.30h).  Cycle scoping is attachment, as everywhere else.
OFFERED_EXTERNAL_OFFERS_SQL = """
    SELECT
        eo.enrollment_id,
        eo.attached_cycle_id AS cycle_id,
        eo.outcome,
        CAST('external' AS text) AS source,
        eo.source AS external_source,
        eo.id AS offer_id,
        CAST(NULL AS uuid) AS application_id,
        CAST(NULL AS uuid) AS job_id,
        eo.company_id,
        COALESCE(CAST(eo.offered_on AS timestamptz), eo.created_at) AS extended_at,
        eo.status,
        CAST(NULL AS timestamptz) AS terminated_at
    FROM external_offers eo
    WHERE eo.status IN ('offered', 'accepted', 'declined')
"""


_ACCEPTED_CTES = f"""
    WITH accepted_portal AS ({ACCEPTED_PORTAL_OFFERS_SQL}),
         accepted_external AS ({ACCEPTED_EXTERNAL_OFFERS_SQL})
"""

_OFFER_FACTS_SQL = f"""
    {_ACCEPTED_CTES}
    SELECT
        EXISTS (
            SELECT 1 FROM accepted_portal
            WHERE enrollment_id = :enrollment_id AND outcome = 'placement'
            UNION ALL
            SELECT 1 FROM accepted_external
            WHERE enrollment_id = :enrollment_id AND outcome = 'placement'
        ) AS placement_placed_global,
        EXISTS (
            SELECT 1 FROM accepted_portal
            WHERE enrollment_id = :enrollment_id
              AND cycle_id = :cycle_id
              AND outcome = 'internship'
            UNION ALL
            SELECT 1 FROM accepted_external
            WHERE enrollment_id = :enrollment_id
              AND cycle_id = :cycle_id
              AND outcome = 'internship'
        ) AS internship_placed_in_cycle,
        (
            SELECT count(*) FROM accepted_portal
            WHERE enrollment_id = :enrollment_id AND cycle_id = :cycle_id
        ) + (
            SELECT count(*) FROM accepted_external
            WHERE enrollment_id = :enrollment_id AND cycle_id = :cycle_id
        ) AS cap_used
"""

_PLACEMENT_ENROLLMENTS_SQL = f"""
    {_ACCEPTED_CTES}
    SELECT DISTINCT accepted.enrollment_id
    FROM (
        SELECT enrollment_id FROM accepted_portal WHERE outcome = 'placement'
        UNION ALL
        SELECT enrollment_id FROM accepted_external WHERE outcome = 'placement'
    ) accepted
    WHERE accepted.enrollment_id = ANY(:enrollment_ids)
    ORDER BY accepted.enrollment_id
"""


@dataclass(frozen=True, slots=True)
class OfferFacts:
    """The three M12a derivations one student/cycle verdict consumes."""

    placement_placed_global: bool
    internship_placed_in_cycle: bool
    cap_used: int


async def offer_facts(
    executor: Executor,
    enrollment_id: UUID,
    cycle_id: UUID | None,
) -> OfferFacts:
    """Load DER-1 and both cycle-local facts in one database round trip."""
    row = (
        await executor.execute(
            sa.text(_OFFER_FACTS_SQL),
            {"enrollment_id": enrollment_id, "cycle_id": cycle_id},
        )
    ).mappings().one()
    return OfferFacts(
        placement_placed_global=bool(row["placement_placed_global"]),
        internship_placed_in_cycle=bool(row["internship_placed_in_cycle"]),
        cap_used=int(row["cap_used"]),
    )


async def placement_placed_global(executor: Executor, enrollment_id: UUID) -> bool:
    """DER-1: an accepted placement offer from either source, in any cycle."""
    return (await offer_facts(executor, enrollment_id, None)).placement_placed_global


async def internship_placed_in_cycle(
    executor: Executor, enrollment_id: UUID, cycle_id: UUID
) -> bool:
    """ELG-3.6: an accepted internship offer inside one dedicated cycle."""
    return (
        await offer_facts(executor, enrollment_id, cycle_id)
    ).internship_placed_in_cycle


async def cap_used(executor: Executor, enrollment_id: UUID, cycle_id: UUID) -> int:
    """ELG-3.7: accepted portal plus attached external offers in one cycle."""
    return (await offer_facts(executor, enrollment_id, cycle_id)).cap_used


async def placement_placed_enrollments(
    executor: Executor, enrollment_ids: tuple[UUID, ...] | list[UUID]
) -> frozenset[UUID]:
    """Batch DER-1 for roster previews without one query per member."""
    if not enrollment_ids:
        return frozenset()
    rows = (
        await executor.execute(
            sa.text(_PLACEMENT_ENROLLMENTS_SQL),
            {"enrollment_ids": list(enrollment_ids)},
        )
    ).scalars().all()
    return frozenset(cast(UUID, row) for row in rows)
