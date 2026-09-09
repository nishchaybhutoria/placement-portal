"""One lock order for every accepted-offer state mutation.

The enrollment row is the cross-cycle, cross-source mutex required by G4.  A
cap is cycle-local, so the second phase locks portal and attached-external offer
rows in every requested cycle.  The final phase locks the target application
and every application/offer the acceptance cascade can touch.  IDs are sorted
inside every phase and a batch locks *all* enrollments before any offer row;
calling a per-student helper in a loop would reintroduce an AB/BA deadlock.

Portal accept, open-cycle recording, expiry and external-offer loaders call this
helper rather than spelling out a partial ``FOR UPDATE`` sequence of their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.shared import CycleKind, Outcome
from app.modules.applications.models import Application
from app.modules.cycles.models import Cycle
from app.modules.identity.models import Enrollment
from app.modules.jobs.models import Job
from app.modules.offers.models import ExternalOffer, Offer


@dataclass(frozen=True, slots=True)
class AcceptanceLockRequest:
    enrollment_id: UUID
    cycle_id: UUID | None
    application_id: UUID | None
    outcome: Outcome | None
    cycle_kind: CycleKind | None
    external_offer_id: UUID | None = None


async def lock_acceptance_state(
    tx: AsyncSession,
    requests: tuple[AcceptanceLockRequest, ...],
    *,
    lock: bool,
) -> frozenset[UUID]:
    """Acquire enrollment → in-cycle offers → cascade targets for a batch."""
    if not requests:
        return frozenset()

    ordered = tuple(
        sorted(
            set(requests),
            key=lambda item: (
                item.enrollment_id.int,
                item.cycle_id.int if item.cycle_id else -1,
                item.application_id.int if item.application_id else -1,
                item.external_offer_id.int if item.external_offer_id else -1,
                item.outcome.value if item.outcome else "",
            ),
        )
    )
    enrollment_ids = tuple(
        sorted({row.enrollment_id for row in ordered}, key=lambda item: item.int)
    )

    # Phase 1: all enrollment mutexes first, in one deterministic order.
    enrollment_statement = (
        sa.select(Enrollment.id).where(Enrollment.id.in_(enrollment_ids)).order_by(Enrollment.id)
    )
    if lock:
        enrollment_statement = enrollment_statement.with_for_update(of=Enrollment)
    found = (await tx.execute(enrollment_statement)).scalars().all()

    # Phase 2 begins by locking named external targets.  Their outcome and
    # attachment are mutable, so an external status loader must not describe
    # its cascade from an unlocked preliminary read.  A request with no cycle
    # and no outcome asks this helper to resolve both under the enrollment
    # mutex and target-row lock; the resolved request drives every later lock.
    external_target_ids = tuple(
        sorted(
            {row.external_offer_id for row in ordered if row.external_offer_id is not None},
            key=lambda item: item.int,
        )
    )
    resolved_external: dict[UUID, tuple[UUID | None, Outcome, CycleKind]] = {}
    if external_target_ids:
        target_external_statement = (
            sa.select(
                ExternalOffer.id,
                ExternalOffer.attached_cycle_id,
                ExternalOffer.outcome,
                Cycle.kind,
            )
            .select_from(ExternalOffer)
            .outerjoin(Cycle, Cycle.id == ExternalOffer.attached_cycle_id)
            .where(ExternalOffer.id.in_(external_target_ids))
            .order_by(ExternalOffer.id)
        )
        if lock:
            target_external_statement = target_external_statement.with_for_update(of=ExternalOffer)
        target_rows = (await tx.execute(target_external_statement)).all()
        for external_id, attached_cycle_id, outcome, kind in target_rows:
            resolved_external[external_id] = (
                attached_cycle_id,
                Outcome(outcome),
                CycleKind(kind) if kind is not None else CycleKind.OPEN,
            )

    effective: list[AcceptanceLockRequest] = []
    for request in ordered:
        if (
            request.external_offer_id in resolved_external
            and request.cycle_id is None
            and request.outcome is None
        ):
            cycle_id, outcome, cycle_kind = resolved_external[
                cast(UUID, request.external_offer_id)
            ]
            effective.append(
                AcceptanceLockRequest(
                    enrollment_id=request.enrollment_id,
                    cycle_id=cycle_id,
                    application_id=request.application_id,
                    outcome=outcome,
                    cycle_kind=cycle_kind,
                    external_offer_id=request.external_offer_id,
                )
            )
        else:
            effective.append(request)

    # Continue phase 2 with cycle-local cap rows.  Pair iteration itself is
    # sorted, and each query orders row IDs, so overlapping batches cannot invert.
    pairs: tuple[tuple[UUID, UUID], ...] = tuple(
        sorted(
            {
                (row.enrollment_id, cast(UUID, row.cycle_id))
                for row in effective
                if row.cycle_id is not None
            },
            key=lambda item: (item[0].int, item[1].int),
        )
    )
    for enrollment_id, cycle_id in pairs:
        portal_statement = (
            sa.select(Offer.id)
            .join(Application, Application.id == Offer.application_id)
            .join(Job, Job.id == Application.job_id)
            .where(
                Application.enrollment_id == enrollment_id,
                Job.cycle_id == cycle_id,
            )
            .order_by(Offer.id)
        )
        if lock:
            portal_statement = portal_statement.with_for_update(of=Offer)
        await tx.execute(portal_statement)

        external_statement = (
            sa.select(ExternalOffer.id)
            .where(
                ExternalOffer.enrollment_id == enrollment_id,
                ExternalOffer.attached_cycle_id == cycle_id,
            )
            .order_by(ExternalOffer.id)
        )
        if lock:
            external_statement = external_statement.with_for_update(of=ExternalOffer)
        await tx.execute(external_statement)

    # Phase 3: targets.  The target itself is always locked.  Placement adds
    # every placement application globally; dedicated internship adds its same
    # cycle; open internship deliberately adds no siblings (OFR-3).
    target_conditions: list[sa.ColumnElement[bool]] = []
    for request in effective:
        own = (
            Application.id == request.application_id
            if request.application_id is not None
            else sa.false()
        )
        if request.outcome is Outcome.PLACEMENT:
            cascade = sa.and_(
                Application.enrollment_id == request.enrollment_id,
                Job.outcome == Outcome.PLACEMENT.value,
            )
        elif request.outcome is Outcome.INTERNSHIP and request.cycle_kind is CycleKind.INTERNSHIP:
            cascade = sa.and_(
                Application.enrollment_id == request.enrollment_id,
                Job.cycle_id == request.cycle_id,
                Job.outcome == Outcome.INTERNSHIP.value,
            )
        else:
            cascade = sa.false()
        target_conditions.append(sa.or_(own, cascade))

    application_statement = (
        sa.select(Application.id)
        .join(Job, Job.id == Application.job_id)
        .where(sa.or_(*target_conditions))
        .order_by(Application.id)
    )
    if lock:
        application_statement = application_statement.with_for_update(of=Application)
    application_ids = (await tx.execute(application_statement)).scalars().all()

    if application_ids:
        cascade_offer_statement = (
            sa.select(Offer.id).where(Offer.application_id.in_(application_ids)).order_by(Offer.id)
        )
        if lock:
            cascade_offer_statement = cascade_offer_statement.with_for_update(of=Offer)
        await tx.execute(cascade_offer_statement)

    return frozenset(found)
