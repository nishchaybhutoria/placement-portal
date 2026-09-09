"""Offer, external-offer, and student dashboard read models (M12f)."""

from __future__ import annotations

from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.authz import require_staff_cycle
from app.core.errors import (
    INVALID_TRANSITION,
    OFFER_CAP_REACHED,
    STALE_VIEW,
    AuthorizationDenied,
)
from app.core.plan import ActorContext, Reason, ScopeIds
from app.core.registry import Registry
from app.domain.gates import evaluate_acceptance_constraints, evaluate_offer_deadline
from app.domain.policy import resolve_policy
from app.domain.shared import (
    ApplicationStatus,
    CycleKind,
    ExternalStatus,
    RuleDomain,
)
from app.domain.transitions import EventHistoryItem, compute_restore_candidates
from app.modules.applications.verdict import gate_overrides
from app.modules.cycles.commands import fetch_policy
from app.modules.offers.commands import _load_offer_applications
from app.modules.offers.derivations import offer_facts
from app.modules.offers.external import ExternalOfferRow, _external_offer
from app.modules.offers.planning import OfferApplication
from app.modules.offers.termination import _candidate_payload, _duplicate_restore_target
from app.modules.overrides.service import applicable


def _engine(request: Request) -> AsyncEngine:
    return cast(AsyncEngine, request.app.state.database_engine)


def _permission(
    allowed: bool, reason: str | None = None, human: str | None = None
) -> dict[str, object]:
    return {"allowed": allowed, "reason": reason, "human": human}


def _denied(reason: Reason) -> dict[str, object]:
    return _permission(False, reason.code, reason.human)


async def _history(tx: AsyncSession, enrollment_id: UUID) -> tuple[EventHistoryItem, ...]:
    rows = (
        (
            await tx.execute(
                sa.text(
                    "SELECT ev.event_seq, ev.application_id, ev.event_type, ev.from_status, "
                    "ev.to_status, ev.from_round_id, ev.to_round_id, ev.payload "
                    "FROM application_events ev JOIN applications a ON a.id = ev.application_id "
                    "WHERE a.enrollment_id = :id ORDER BY ev.event_seq"
                ),
                {"id": enrollment_id},
            )
        )
        .mappings()
        .all()
    )
    from app.domain.shared import EventType

    return tuple(
        EventHistoryItem(
            sequence=int(row["event_seq"]),
            application_id=cast(UUID, row["application_id"]),
            event_type=EventType(row["event_type"]),
            from_status=(
                ApplicationStatus(row["from_status"]) if row["from_status"] is not None else None
            ),
            to_status=(
                ApplicationStatus(row["to_status"]) if row["to_status"] is not None else None
            ),
            from_round_id=cast("UUID | None", row["from_round_id"]),
            to_round_id=cast("UUID | None", row["to_round_id"]),
            payload=dict(row["payload"] or {}),
        )
        for row in rows
    )


def _restoration_candidates(
    *,
    acceptance_id: UUID,
    history: tuple[EventHistoryItem, ...],
    applications: tuple[OfferApplication, ...],
) -> list[dict[str, object]]:
    candidates = compute_restore_candidates(
        acceptance_offer_id=acceptance_id,
        history=history,
        current_statuses={row.application_id: row.status for row in applications},
    )
    by_id = {row.application_id: row for row in applications}
    return [
        _candidate_payload(
            candidate,
            by_id[candidate.application_id],
            selected=None,
            duplicate_application=_duplicate_restore_target(
                candidate, by_id[candidate.application_id], applications
            ),
        )
        for candidate in candidates
    ]


def _offer_row(
    application: OfferApplication,
    *,
    archived: bool,
    cancelled: bool,
    restoration_candidates: list[dict[str, object]],
) -> dict[str, object]:
    frozen = archived or cancelled
    open_offer = (
        application.current_offer_id is not None
        and application.current_offer_response is None
        and not application.current_offer_terminated
    )
    can_extend = not frozen and application.status in {
        ApplicationStatus.IN_PROGRESS,
        ApplicationStatus.PENDING_OFFER,
    }
    can_terminate = (
        not frozen
        and application.status in {ApplicationStatus.OFFERED, ApplicationStatus.ACCEPTED}
        and application.current_offer_id is not None
        and not application.current_offer_terminated
        and (
            (application.status is ApplicationStatus.OFFERED and open_offer)
            or (
                application.status is ApplicationStatus.ACCEPTED
                and application.current_offer_response is not None
            )
        )
    )
    can_re_extend = (
        not frozen
        and application.current_offer_id is not None
        and (
            (
                application.status is ApplicationStatus.DECLINED
                and application.current_offer_response is not None
                and not application.current_offer_terminated
            )
            or (
                application.status is ApplicationStatus.OFFER_TERMINATED
                and application.current_offer_terminated
            )
        )
    )
    frozen_human = (
        "The cycle is archived" if archived else "The job is cancelled" if cancelled else None
    )
    return {
        "application_id": str(application.application_id),
        "enrollment_id": str(application.enrollment_id),
        "full_name": application.full_name,
        "email": application.email,
        "roll_number": application.roll_number,
        "status": application.status.value,
        "current_round_id": (
            str(application.current_round_id) if application.current_round_id else None
        ),
        "offer": (
            {
                "id": str(application.current_offer_id),
                "deadline_at": (
                    application.current_offer_deadline.isoformat()
                    if application.current_offer_deadline
                    else None
                ),
                "response": (
                    application.current_offer_response.value
                    if application.current_offer_response
                    else None
                ),
                "terminated": application.current_offer_terminated,
            }
            if application.current_offer_id
            else None
        ),
        "offer_count": application.offer_count,
        "restoration_candidates": restoration_candidates,
        "actions": {
            "extend": _permission(
                can_extend,
                None if can_extend else INVALID_TRANSITION,
                None if can_extend else frozen_human or "This application is not extendable",
            ),
            "terminate": _permission(
                can_terminate,
                None if can_terminate else INVALID_TRANSITION,
                None
                if can_terminate
                else frozen_human or "There is no current offered or accepted offer",
            ),
            "re_extend": _permission(
                can_re_extend,
                None if can_re_extend else INVALID_TRANSITION,
                None
                if can_re_extend
                else frozen_human or "Only a declined or terminated offer can be re-extended",
            ),
        },
    }


async def staff_job_offers(engine: AsyncEngine, *, job_id: UUID) -> dict[str, object] | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as tx:
        job = (
            (
                await tx.execute(
                    sa.text(
                        "SELECT j.id, j.title, j.outcome, j.cancelled_at, j.cycle_id, "
                        "company.name AS company, c.name AS cycle, c.kind AS cycle_kind, "
                        "c.archived_at, j.offer_acceptance_deadline "
                        "FROM jobs j JOIN companies company ON company.id = j.company_id "
                        "JOIN cycles c ON c.id = j.cycle_id WHERE j.id = :id"
                    ),
                    {"id": job_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            return None
        applications = await _load_offer_applications(tx, job_id=job_id)
        histories: dict[UUID, tuple[EventHistoryItem, ...]] = {}
        all_for_enrollment: dict[UUID, tuple[OfferApplication, ...]] = {}
        rows: list[dict[str, object]] = []
        for application in applications:
            candidates: list[dict[str, object]] = []
            if (
                application.status is ApplicationStatus.ACCEPTED
                and application.current_offer_id is not None
            ):
                enrollment_apps = all_for_enrollment.get(application.enrollment_id)
                if enrollment_apps is None:
                    enrollment_apps = await _load_offer_applications(
                        tx, enrollment_ids=(application.enrollment_id,)
                    )
                    all_for_enrollment[application.enrollment_id] = enrollment_apps
                history = histories.get(application.enrollment_id)
                if history is None:
                    history = await _history(tx, application.enrollment_id)
                    histories[application.enrollment_id] = history
                candidates = _restoration_candidates(
                    acceptance_id=application.current_offer_id,
                    history=history,
                    applications=enrollment_apps,
                )
            rows.append(
                _offer_row(
                    application,
                    archived=job["archived_at"] is not None,
                    cancelled=job["cancelled_at"] is not None,
                    restoration_candidates=candidates,
                )
            )
        cycle_kind = CycleKind(job["cycle_kind"])
        frozen = job["archived_at"] is not None or job["cancelled_at"] is not None
        any_extendable = any(
            cast(
                dict[str, object],
                cast(dict[str, object], row["actions"])["extend"],
            )["allowed"]
            is True
            for row in rows
        )
        return {
            "job": {
                "id": str(job["id"]),
                "title": str(job["title"]),
                "company": str(job["company"]),
                "outcome": str(job["outcome"]),
                "cancelled": job["cancelled_at"] is not None,
                "offer_acceptance_deadline": (
                    job["offer_acceptance_deadline"].isoformat()
                    if job["offer_acceptance_deadline"]
                    else None
                ),
            },
            "cycle": {
                "id": str(job["cycle_id"]),
                "name": str(job["cycle"]),
                "kind": cycle_kind.value,
                "archived": job["archived_at"] is not None,
            },
            "applications": rows,
            "counts": {
                status.value: sum(1 for row in applications if row.status is status)
                for status in ApplicationStatus
            },
            "actions": {
                "extend": _permission(
                    not frozen and any_extendable,
                    None if not frozen and any_extendable else INVALID_TRANSITION,
                    None
                    if not frozen and any_extendable
                    else "The job is read-only"
                    if frozen
                    else "No application is extendable",
                ),
                "record_open_outcome": _permission(
                    not frozen and cycle_kind is CycleKind.OPEN,
                    None if not frozen and cycle_kind is CycleKind.OPEN else INVALID_TRANSITION,
                    None
                    if not frozen and cycle_kind is CycleKind.OPEN
                    else "Staff-recorded outcomes are only available for open-cycle jobs",
                ),
            },
        }


async def _offer_permissions(
    tx: AsyncSession,
    application: OfferApplication,
    *,
    archived: bool,
    cancelled: bool,
    now: datetime,
) -> tuple[dict[str, object], dict[str, object]]:
    structural: list[Reason] = []
    if archived:
        structural.append(Reason(code=INVALID_TRANSITION, human="The cycle is archived"))
    if cancelled:
        structural.append(Reason(code=INVALID_TRANSITION, human="The job is cancelled"))
    if application.cycle_kind is CycleKind.OPEN:
        structural.append(
            Reason(
                code=INVALID_TRANSITION,
                human="Open-cycle outcomes are recorded by staff",
            )
        )
    if (
        application.status is not ApplicationStatus.OFFERED
        or application.current_offer_id is None
        or application.current_offer_response is not None
        or application.current_offer_terminated
    ):
        structural.append(Reason(code=STALE_VIEW, human="This is not a current unanswered offer"))
    overrides = await applicable(
        tx,
        (
            RuleDomain.OFFER_DEADLINE,
            RuleDomain.OUTCOME_GATE,
            RuleDomain.OFFER_CAP,
        ),
        ScopeIds(
            cycle_id=application.cycle_id,
            job_id=application.job_id,
            enrollment_id=application.enrollment_id,
            application_id=application.application_id,
        ),
    )
    resolved = gate_overrides(overrides)
    deadline = evaluate_offer_deadline(
        now=now,
        deadline=application.current_offer_deadline,
        overrides=resolved,
    )
    decline_failures = [*structural, *deadline.failures]
    facts = await offer_facts(tx, application.enrollment_id, application.cycle_id)
    policy = resolve_policy(
        application.cycle_kind,
        cycle_policy=await fetch_policy(tx, application.cycle_id),
    )
    constraints = evaluate_acceptance_constraints(
        outcome=application.outcome,
        cycle_kind=application.cycle_kind,
        placement_placed_global=facts.placement_placed_global,
        internship_placed_in_cycle=facts.internship_placed_in_cycle,
        max_accepted_offers=policy.max_accepted_offers.value,
        cap_used=facts.cap_used,
        overrides=resolved,
    )
    accept_failures = [*decline_failures, *constraints.failures]
    return (
        _permission(True) if not accept_failures else _denied(accept_failures[0]),
        _permission(True) if not decline_failures else _denied(decline_failures[0]),
    )


def _external_payload(
    row: ExternalOfferRow,
    *,
    actions: dict[str, dict[str, object]] | None = None,
    read_only: bool = False,
) -> dict[str, object]:
    return {
        "id": str(row.id),
        "enrollment_id": str(row.enrollment_id),
        "student": row.full_name,
        "email": row.email,
        "roll_number": row.roll_number,
        "company": {"id": str(row.company_id), "name": row.company_name},
        "outcome": row.outcome.value,
        "source": row.source.value,
        "ctc_lpa": str(row.ctc_lpa) if row.ctc_lpa is not None else None,
        "stipend_month": (str(row.stipend_month) if row.stipend_month is not None else None),
        "status": row.status.value,
        "offered_on": row.offered_on.isoformat() if row.offered_on else None,
        "responded_on": row.responded_on.isoformat() if row.responded_on else None,
        "source_application_id": (
            str(row.source_application_id) if row.source_application_id else None
        ),
        "attached_cycle": (
            {
                "id": str(row.attached_cycle_id),
                "name": row.attached_cycle_name,
                "kind": (row.attached_cycle_kind.value if row.attached_cycle_kind else None),
            }
            if row.attached_cycle_id
            else None
        ),
        "notes": row.notes,
        "read_only": read_only,
        "actions": actions or {},
    }


async def student_dashboard(engine: AsyncEngine, enrollment_id: UUID) -> dict[str, object]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as tx:
        now = cast(datetime, await tx.scalar(sa.select(sa.func.now())))
        applications = await _load_offer_applications(tx, enrollment_ids=(enrollment_id,))
        cycle_rows = (
            (
                await tx.execute(
                    sa.text(
                        "SELECT c.id, c.archived_at, j.id AS job_id, j.cancelled_at "
                        "FROM jobs j JOIN cycles c ON c.id = j.cycle_id "
                        "JOIN applications a ON a.job_id = j.id "
                        "WHERE a.enrollment_id = :id"
                    ),
                    {"id": enrollment_id},
                )
            )
            .mappings()
            .all()
        )
        mutable = {
            cast(UUID, row["job_id"]): (
                row["archived_at"] is not None,
                row["cancelled_at"] is not None,
            )
            for row in cycle_rows
        }
        offer_rows: list[dict[str, object]] = []
        for application in applications:
            if application.current_offer_id is None:
                continue
            archived, cancelled = mutable.get(application.job_id, (False, False))
            accept, decline = await _offer_permissions(
                tx,
                application,
                archived=archived,
                cancelled=cancelled,
                now=now,
            )
            offer_rows.append(
                {
                    "offer_id": str(application.current_offer_id),
                    "application_id": str(application.application_id),
                    "cycle_id": str(application.cycle_id),
                    "cycle": application.cycle_name,
                    "job_id": str(application.job_id),
                    "job": application.job_title,
                    "company": application.company_name,
                    "outcome": application.outcome.value,
                    "status": application.status.value,
                    "deadline_at": (
                        application.current_offer_deadline.isoformat()
                        if application.current_offer_deadline
                        else None
                    ),
                    "response": (
                        application.current_offer_response.value
                        if application.current_offer_response
                        else None
                    ),
                    "terminated": application.current_offer_terminated,
                    "actions": {"accept": accept, "decline": decline},
                }
            )
        external_ids = (
            (
                await tx.execute(
                    sa.text(
                        "SELECT id FROM external_offers WHERE enrollment_id = :id "
                        "ORDER BY offered_on DESC NULLS LAST, id"
                    ),
                    {"id": enrollment_id},
                )
            )
            .scalars()
            .all()
        )
        externals = [
            _external_payload(
                cast(ExternalOfferRow, await _external_offer(tx, item)), read_only=True
            )
            for item in external_ids
        ]
        memberships = (
            (
                await tx.execute(
                    sa.text(
                        "SELECT cm.id, cm.status, cm.auto_created, c.id AS cycle_id, "
                        "c.name, c.kind FROM cycle_memberships cm "
                        "JOIN cycles c ON c.id = cm.cycle_id "
                        "WHERE cm.enrollment_id = :id ORDER BY c.name"
                    ),
                    {"id": enrollment_id},
                )
            )
            .mappings()
            .all()
        )
        upcoming = (
            (
                await tx.execute(
                    sa.text(
                        "SELECT a.id AS application_id, j.title AS job, c.name AS cycle, "
                        "jr.name AS round, COALESCE(ars.scheduled_at_override, jr.scheduled_at) "
                        "AS scheduled_at, COALESCE(ars.venue_override, jr.venue) AS venue "
                        "FROM applications a JOIN jobs j ON j.id = a.job_id "
                        "JOIN cycles c ON c.id = j.cycle_id "
                        "JOIN application_round_states ars ON ars.application_id = a.id "
                        "JOIN job_rounds jr ON jr.id = ars.round_id "
                        "WHERE a.enrollment_id = :id AND a.status = 'in_progress' "
                        "AND ars.result = 'pending' ORDER BY scheduled_at NULLS LAST"
                    ),
                    {"id": enrollment_id},
                )
            )
            .mappings()
            .all()
        )
        discipline = (
            (
                await tx.execute(
                    sa.text(
                        "SELECT (SELECT count(*) FROM strikes WHERE enrollment_id = :id "
                        "AND is_active) AS strikes, "
                        "(SELECT count(*) FROM penalties WHERE enrollment_id = :id "
                        "AND is_active) AS penalties"
                    ),
                    {"id": enrollment_id},
                )
            )
            .mappings()
            .one()
        )
        return {
            "enrollment_id": str(enrollment_id),
            "memberships": [
                {
                    "id": str(row["id"]),
                    "status": str(row["status"]),
                    "auto_created": bool(row["auto_created"]),
                    "cycle": {
                        "id": str(row["cycle_id"]),
                        "name": str(row["name"]),
                        "kind": str(row["kind"]),
                    },
                }
                for row in memberships
            ],
            "applications": [
                {
                    "id": str(row.application_id),
                    "job": row.job_title,
                    "company": row.company_name,
                    "cycle": row.cycle_name,
                    "status": row.status.value,
                }
                for row in applications
            ],
            "upcoming_rounds": [
                {
                    "application_id": str(row["application_id"]),
                    "job": str(row["job"]),
                    "cycle": str(row["cycle"]),
                    "round": str(row["round"]),
                    "scheduled_at": (
                        row["scheduled_at"].isoformat() if row["scheduled_at"] else None
                    ),
                    "venue": str(row["venue"]) if row["venue"] else None,
                }
                for row in upcoming
            ],
            "offers": offer_rows,
            "external_offers": externals,
            "discipline": {
                "active_strikes": int(discipline["strikes"]),
                "active_penalties": int(discipline["penalties"]),
            },
        }


async def _all_external_rows(tx: AsyncSession) -> list[ExternalOfferRow]:
    ids = (
        (
            await tx.execute(
                sa.text("SELECT id FROM external_offers ORDER BY offered_on DESC NULLS LAST, id")
            )
        )
        .scalars()
        .all()
    )
    found: list[ExternalOfferRow] = []
    for item in ids:
        row = await _external_offer(tx, item)
        if row is not None:
            found.append(row)
    return found


async def staff_external_offers(
    engine: AsyncEngine,
    *,
    q: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
    attached: bool | None = None,
) -> dict[str, object]:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as tx:
        rows = await _all_external_rows(tx)
        query = (q or "").strip().casefold()
        filtered = [
            row
            for row in rows
            if (
                not query
                or query in row.full_name.casefold()
                or query in row.company_name.casefold()
            )
            and (status is None or row.status.value == status)
            and (outcome is None or row.outcome.value == outcome)
            and (attached is None or (row.attached_cycle_id is not None) is attached)
        ]
        companies = (
            (
                await tx.execute(
                    sa.text("SELECT id, name FROM companies WHERE is_active ORDER BY name")
                )
            )
            .mappings()
            .all()
        )
        enrollments = (
            (
                await tx.execute(
                    sa.text(
                        "SELECT e.id, u.full_name, u.email, e.roll_number "
                        "FROM enrollments e JOIN users u ON u.id = e.user_id "
                        "WHERE e.is_current ORDER BY u.full_name, u.email"
                    )
                )
            )
            .mappings()
            .all()
        )
        offer_payloads: list[dict[str, object]] = []
        for row in filtered:
            item = _external_payload(
                row,
                actions={
                    "update": _permission(True),
                    "delete": _permission(True),
                },
            )
            item["restoration_candidates"] = (
                _restoration_candidates(
                    acceptance_id=row.id,
                    history=await _history(tx, row.enrollment_id),
                    applications=await _load_offer_applications(
                        tx, enrollment_ids=(row.enrollment_id,)
                    ),
                )
                if row.status is ExternalStatus.ACCEPTED
                else []
            )
            offer_payloads.append(item)
        return {
            "filters": {
                "q": q,
                "status": status,
                "outcome": outcome,
                "attached": attached,
            },
            "actions": {"create": _permission(True)},
            "companies": [{"id": str(row["id"]), "name": str(row["name"])} for row in companies],
            "enrollments": [
                {
                    "id": str(row["id"]),
                    "full_name": str(row["full_name"]),
                    "email": str(row["email"]),
                    "roll_number": (str(row["roll_number"]) if row["roll_number"] else None),
                }
                for row in enrollments
            ],
            "offers": offer_payloads,
        }


async def staff_cycle_external_offers(
    engine: AsyncEngine, *, cycle_id: UUID
) -> dict[str, object] | None:
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as tx:
        cycle = (
            (
                await tx.execute(
                    sa.text("SELECT id, name, kind, archived_at FROM cycles WHERE id = :id"),
                    {"id": cycle_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if cycle is None:
            return None
        cycle_kind = CycleKind(cycle["kind"])
        policy = resolve_policy(
            cycle_kind,
            cycle_policy=await fetch_policy(tx, cycle_id),
        )
        rows = await _all_external_rows(tx)
        attached_rows = [row for row in rows if row.attached_cycle_id == cycle_id]
        pool_rows = [
            row
            for row in rows
            if row.attached_cycle_id is None
            and cycle_kind is not CycleKind.OPEN
            and row.outcome.value == cycle_kind.value
        ]

        async def payload(row: ExternalOfferRow, *, is_attached: bool) -> dict[str, object]:
            action = True
            reason = None
            human = None
            if cycle["archived_at"] is not None:
                action, reason, human = False, INVALID_TRANSITION, "The cycle is archived"
            elif not is_attached and row.status is ExternalStatus.ACCEPTED:
                facts = await offer_facts(tx, row.enrollment_id, cycle_id)
                if (
                    policy.max_accepted_offers.value is not None
                    and facts.cap_used >= policy.max_accepted_offers.value
                ):
                    action, reason, human = (
                        False,
                        OFFER_CAP_REACHED,
                        "The cycle's accepted-offer cap is already reached",
                    )
            actions = (
                {"detach": _permission(action, reason, human)}
                if is_attached
                else {"attach": _permission(action, reason, human)}
            )
            return _external_payload(row, actions=actions)

        attached_payload = [await payload(row, is_attached=True) for row in attached_rows]
        pool_payload = [await payload(row, is_attached=False) for row in pool_rows]
        return {
            "cycle": {
                "id": str(cycle["id"]),
                "name": str(cycle["name"]),
                "kind": cycle_kind.value,
                "archived": cycle["archived_at"] is not None,
            },
            "policy": {"max_accepted_offers": policy.max_accepted_offers.value},
            "attached": attached_payload,
            "unattached_pool": pool_payload,
        }


async def _staff_job_offers_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    screen = await staff_job_offers(_engine(request), job_id=id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cycle_id = UUID(cast(str, cast(dict[str, object], screen["cycle"])["id"]))
    require_staff_cycle(actor, cycle_id)
    return screen


async def _staff_external_screen(
    request: Request,
    q: str | None = None,
    status: str | None = None,
    outcome: str | None = None,
    attached: bool | None = None,
) -> dict[str, object]:
    return await staff_external_offers(
        _engine(request), q=q, status=status, outcome=outcome, attached=attached
    )


async def _staff_cycle_external_screen(
    request: Request, id: UUID, actor: ActorContext
) -> dict[str, object]:
    require_staff_cycle(actor, id)
    screen = await staff_cycle_external_offers(_engine(request), cycle_id=id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Cycle not found")
    return screen


async def _dashboard_screen(request: Request, actor: ActorContext) -> dict[str, object]:
    if actor.current_enrollment_id is None:
        raise AuthorizationDenied(authenticated=actor.user_id is not None)
    return await student_dashboard(_engine(request), actor.current_enrollment_id)


def register_offer_screens(registry: Registry) -> None:
    registry.screen(id="staff/job/{id}/offers", roles=("staff",))(_staff_job_offers_screen)
    registry.screen(id="staff/external", roles=("staff",))(_staff_external_screen)
    registry.screen(id="staff/cycle/{id}/external", roles=("staff",))(_staff_cycle_external_screen)
    registry.screen(id="me/dashboard", roles=("student",))(_dashboard_screen)
