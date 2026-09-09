"""Offer termination, selective restoration, and re-extension (OFR-5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    APPLICATION_NOT_FOUND,
    CYCLE_NOT_FOUND,
    DUPLICATE_APPLICATION,
    INVALID_TRANSITION,
    JOB_NOT_FOUND,
    NOT_OFFERED,
    OFFER_TERMINATED,
    STALE_VIEW,
)
from app.core.plan import (
    ActorContext,
    Deferred,
    Event,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.domain.shared import (
    ApplicationStatus,
    CycleKind,
    EventType,
    StrikeSource,
    TerminationKind,
)
from app.domain.transitions import (
    EventHistoryItem,
    RestoreCandidate,
    TransitionActor,
    TransitionContext,
    compute_restore_candidates,
    decide_transition,
)
from app.modules.cycles.commands import CycleRow, fetch_cycle
from app.modules.discipline.awards import (
    EnrollmentDiscipline,
    StrikeIntent,
    award_direct_penalty,
    award_strikes,
    load_discipline,
    resolve_threshold,
)
from app.modules.jobs.commands import JobRow, fetch_job
from app.modules.notifications.wording import humanise
from app.modules.offers.commands import _load_offer_applications
from app.modules.offers.locking import AcceptanceLockRequest, lock_acceptance_state
from app.modules.offers.planning import OfferApplication, plan_extension

DisciplineChoice = Literal["strike", "penalty"]


@dataclass(frozen=True, slots=True)
class _PortalIdentity:
    enrollment_id: UUID
    cycle_id: UUID
    job_id: UUID
    outcome: str
    cycle_kind: CycleKind


@dataclass(frozen=True, slots=True)
class OfferInterventionState:
    scope_ids: ScopeIds
    cycle_archived: bool
    now: datetime
    cycle: CycleRow | None
    job: JobRow | None
    target: OfferApplication | None
    applications: tuple[OfferApplication, ...]
    history: tuple[EventHistoryItem, ...]
    discipline: EnrollmentDiscipline | None
    threshold: int | None


class RestoreSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_id: UUID
    deadline_at: datetime | None = None


class TerminateOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    application_id: UUID
    offer_id: UUID
    expected_status: ApplicationStatus
    termination_kind: TerminationKind
    reason: str
    restore: list[RestoreSelection] = []
    discipline: DisciplineChoice | None = None
    notify: bool = True

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a termination reason is required")
        return value.strip()

    @model_validator(mode="after")
    def unique_restore_choices(self) -> TerminateOfferInput:
        ids = [row.application_id for row in self.restore]
        if len(ids) != len(set(ids)):
            raise ValueError("each restoration application may be selected only once")
        return self


class TerminateOfferSummary(BaseModel):
    cycle_id: UUID
    job_id: UUID
    application_id: UUID
    offer_id: UUID
    enrollment_id: UUID
    status: ApplicationStatus
    termination_kind: TerminationKind
    reason: str
    automatic_effects: list[dict[str, object]]
    restoration_candidates: list[dict[str, object]]
    restored: list[dict[str, object]]
    discipline: dict[str, object] | None
    notify: bool


class ReExtendOfferInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle_id: UUID
    job_id: UUID
    application_id: UUID
    offer_id: UUID
    expected_status: ApplicationStatus
    reason: str
    deadline_at: datetime | None = None
    notify: bool = True

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("an intervention reason is required")
        return value.strip()


class ReExtendOfferSummary(BaseModel):
    cycle_id: UUID
    job_id: UUID
    application_id: UUID
    previous_offer_id: UUID
    offer_id: UUID
    enrollment_id: UUID
    status: ApplicationStatus
    deadline_at: datetime | None
    notify: bool


async def _portal_identity(
    tx: AsyncSession, *, application_id: UUID, offer_id: UUID
) -> _PortalIdentity | None:
    row = (
        await tx.execute(
            sa.text(
                "SELECT a.enrollment_id, a.job_id, j.cycle_id, j.outcome, c.kind "
                "FROM applications a JOIN jobs j ON j.id = a.job_id "
                "JOIN cycles c ON c.id = j.cycle_id "
                "JOIN offers o ON o.application_id = a.id "
                "WHERE a.id = :application_id AND o.id = :offer_id"
            ),
            {"application_id": application_id, "offer_id": offer_id},
        )
    ).mappings().one_or_none()
    if row is None:
        return None
    return _PortalIdentity(
        enrollment_id=cast(UUID, row["enrollment_id"]),
        cycle_id=cast(UUID, row["cycle_id"]),
        job_id=cast(UUID, row["job_id"]),
        outcome=str(row["outcome"]),
        cycle_kind=CycleKind(row["kind"]),
    )


async def _event_history(
    tx: AsyncSession, enrollment_id: UUID
) -> tuple[EventHistoryItem, ...]:
    rows = (
        await tx.execute(
            sa.text(
                "SELECT ev.event_seq, ev.application_id, ev.event_type, ev.from_status, "
                "ev.to_status, ev.from_round_id, ev.to_round_id, ev.payload "
                "FROM application_events ev "
                "JOIN applications a ON a.id = ev.application_id "
                "WHERE a.enrollment_id = :enrollment_id "
                "ORDER BY ev.event_seq"
            ),
            {"enrollment_id": enrollment_id},
        )
    ).mappings().all()
    return tuple(
        EventHistoryItem(
            sequence=int(row["event_seq"]),
            application_id=cast(UUID, row["application_id"]),
            event_type=EventType(row["event_type"]),
            from_status=(
                ApplicationStatus(row["from_status"])
                if row["from_status"] is not None
                else None
            ),
            to_status=(
                ApplicationStatus(row["to_status"])
                if row["to_status"] is not None
                else None
            ),
            from_round_id=cast("UUID | None", row["from_round_id"]),
            to_round_id=cast("UUID | None", row["to_round_id"]),
            payload=dict(row["payload"] or {}),
        )
        for row in rows
    )


async def _load_intervention(
    tx: AsyncSession,
    *,
    cycle_id: UUID,
    job_id: UUID,
    application_id: UUID,
    offer_id: UUID,
    lock: bool,
    include_discipline: bool,
) -> OfferInterventionState:
    cycle = await fetch_cycle(tx, cycle_id, lock=False)
    job = await fetch_job(tx, cycle_id=cycle_id, job_id=job_id, lock=False)
    identity = await _portal_identity(
        tx, application_id=application_id, offer_id=offer_id
    )
    if identity is not None:
        from app.domain.shared import Outcome

        await lock_acceptance_state(
            tx,
            (
                AcceptanceLockRequest(
                    enrollment_id=identity.enrollment_id,
                    cycle_id=identity.cycle_id,
                    application_id=application_id,
                    outcome=Outcome(identity.outcome),
                    cycle_kind=identity.cycle_kind,
                ),
            ),
            lock=lock,
        )

    # Everything mutable is read after the one centralized lock path.
    cycle = await fetch_cycle(tx, cycle_id, lock=False)
    job = await fetch_job(tx, cycle_id=cycle_id, job_id=job_id, lock=False)
    applications: tuple[OfferApplication, ...] = ()
    target: OfferApplication | None = None
    history: tuple[EventHistoryItem, ...] = ()
    discipline: EnrollmentDiscipline | None = None
    threshold: int | None = None
    if identity is not None:
        applications = await _load_offer_applications(
            tx, enrollment_ids=(identity.enrollment_id,)
        )
        target = next(
            (
                row
                for row in applications
                if row.application_id == application_id
                and row.job_id == job_id
                and row.cycle_id == cycle_id
            ),
            None,
        )
        history = await _event_history(tx, identity.enrollment_id)
        if include_discipline:
            discipline = (await load_discipline(tx, [identity.enrollment_id])).get(
                identity.enrollment_id
            )
            threshold = await resolve_threshold(tx)

    return OfferInterventionState(
        scope_ids=ScopeIds(
            cycle_id=cycle_id,
            job_id=job_id,
            enrollment_id=identity.enrollment_id if identity else None,
            application_id=application_id,
        ),
        cycle_archived=cycle is not None and cycle.archived_at is not None,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        cycle=cycle,
        job=job,
        target=target,
        applications=applications,
        history=history,
        discipline=discipline,
        threshold=threshold,
    )


async def _load_terminate(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> OfferInterventionState:
    if not isinstance(input_value, TerminateOfferInput):
        raise TypeError("terminate_offer requires TerminateOfferInput")
    return await _load_intervention(
        tx,
        cycle_id=input_value.cycle_id,
        job_id=input_value.job_id,
        application_id=input_value.application_id,
        offer_id=input_value.offer_id,
        lock=lock,
        include_discipline=True,
    )


async def _load_re_extend(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> OfferInterventionState:
    if not isinstance(input_value, ReExtendOfferInput):
        raise TypeError("re_extend_offer requires ReExtendOfferInput")
    return await _load_intervention(
        tx,
        cycle_id=input_value.cycle_id,
        job_id=input_value.job_id,
        application_id=input_value.application_id,
        offer_id=input_value.offer_id,
        lock=lock,
        include_discipline=False,
    )


def _target_reasons(
    *,
    cycle: CycleRow | None,
    job: JobRow | None,
    target: OfferApplication | None,
    offer_id: UUID,
    expected_status: ApplicationStatus,
) -> list[Reason]:
    if cycle is None:
        return [Reason(code=CYCLE_NOT_FOUND, human="The cycle does not exist")]
    if job is None:
        return [Reason(code=JOB_NOT_FOUND, human="The job does not exist")]
    if target is None:
        return [
            Reason(
                code=APPLICATION_NOT_FOUND,
                human="The application or offer does not exist for this job",
                path="application_id",
            )
        ]
    reasons: list[Reason] = []
    if target.status is not expected_status:
        reasons.append(
            Reason(
                code=STALE_VIEW,
                human="The application status changed since this intervention was opened",
                path="expected_status",
            )
        )
    if target.current_offer_id != offer_id:
        reasons.append(
            Reason(
                code=STALE_VIEW,
                human="A newer offer row is now current for this application",
                path="offer_id",
            )
        )
    return reasons


def _restore_candidates(
    state: OfferInterventionState, offer_id: UUID
) -> tuple[RestoreCandidate, ...]:
    return compute_restore_candidates(
        acceptance_offer_id=offer_id,
        history=state.history,
        current_statuses={row.application_id: row.status for row in state.applications},
    )


def _candidate_payload(
    candidate: RestoreCandidate,
    application: OfferApplication,
    *,
    selected: RestoreSelection | None,
    duplicate_application: bool,
) -> dict[str, object]:
    return {
        "application_id": str(candidate.application_id),
        "job_id": str(application.job_id),
        "job": application.job_title,
        "company": application.company_name,
        "cycle_id": str(application.cycle_id),
        "cycle": application.cycle_name,
        "current_status": candidate.current_status.value,
        "restore_status": candidate.restore_status.value,
        "target_round_id": (
            str(candidate.restore_round_id) if candidate.restore_round_id else None
        ),
        "requires_fresh_offer": candidate.requires_fresh_offer,
        "deadline_editable": candidate.requires_fresh_offer
        and application.cycle_kind is not CycleKind.OPEN,
        "can_restore": not duplicate_application,
        "blocked_reason": DUPLICATE_APPLICATION if duplicate_application else None,
        "selected": selected is not None,
        "deadline_at": (
            selected.deadline_at.isoformat()
            if selected is not None and selected.deadline_at is not None
            else None
        ),
    }


def _duplicate_restore_target(
    candidate: RestoreCandidate,
    application: OfferApplication,
    applications: tuple[OfferApplication, ...],
) -> bool:
    if candidate.requires_fresh_offer:
        return False
    return any(
        row.application_id != application.application_id
        and row.job_id == application.job_id
        and row.status
        not in {ApplicationStatus.WITHDRAWN, ApplicationStatus.AUTO_WITHDRAWN}
        for row in applications
    )


def _decide_terminate(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """OFR-5: terminate, then restore only explicitly selected causal rows."""
    if not isinstance(input_value, TerminateOfferInput) or not isinstance(
        state, OfferInterventionState
    ):
        raise TypeError("Invalid terminate_offer decision input")
    reasons = _target_reasons(
        cycle=state.cycle,
        job=state.job,
        target=state.target,
        offer_id=input_value.offer_id,
        expected_status=input_value.expected_status,
    )
    if reasons:
        return Rejection(reasons=reasons)
    assert state.cycle is not None and state.target is not None
    target = state.target
    if target.status not in {ApplicationStatus.OFFERED, ApplicationStatus.ACCEPTED}:
        return Rejection(
            reasons=[
                Reason(
                    code=NOT_OFFERED,
                    human="Only an offered or accepted offer can be terminated",
                    path="expected_status",
                )
            ]
        )
    if target.current_offer_terminated:
        return Rejection(
            reasons=[Reason(code=OFFER_TERMINATED, human="The offer is already terminated")]
        )
    if (
        target.status is ApplicationStatus.ACCEPTED
        and target.current_offer_response is None
    ) or (
        target.status is ApplicationStatus.OFFERED
        and target.current_offer_response is not None
    ):
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human="The application and current offer response no longer agree",
                )
            ]
        )
    transition = decide_transition(
        "terminate_offer",
        from_status=target.status,
        to_status=ApplicationStatus.OFFER_TERMINATED,
        actor=TransitionActor.STAFF,
        context=TransitionContext(cycle_kind=target.cycle_kind),
        reason=input_value.reason,
    )
    if isinstance(transition, Rejection):
        return transition

    candidates = _restore_candidates(state, input_value.offer_id)
    by_candidate = {row.application_id: row for row in candidates}
    by_application = {row.application_id: row for row in state.applications}
    selected = {row.application_id: row for row in input_value.restore}
    unavailable = sorted(set(selected) - set(by_candidate), key=lambda item: item.int)
    if unavailable:
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human=(
                        "A selected restoration is no longer in the state produced by "
                        "this acceptance; refresh the preview"
                    ),
                    path=f"restore.{application_id}",
                )
                for application_id in unavailable
            ]
        )

    duplicate_by_id = {
        candidate.application_id: _duplicate_restore_target(
            candidate,
            by_application[candidate.application_id],
            state.applications,
        )
        for candidate in candidates
    }
    blocked_selected = [
        application_id
        for application_id in selected
        if duplicate_by_id[application_id]
    ]
    if blocked_selected:
        return Rejection(
            reasons=[
                Reason(
                    code=DUPLICATE_APPLICATION,
                    human=(
                        "This auto-withdrawn application cannot be restored because "
                        "another active application exists for the same job"
                    ),
                    path=f"restore.{application_id}",
                )
                for application_id in blocked_selected
            ]
        )
    open_deadlines = [
        selection.application_id
        for selection in input_value.restore
        if selection.deadline_at is not None
        and by_application[selection.application_id].cycle_kind is CycleKind.OPEN
    ]
    if open_deadlines:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Open-cycle offers do not carry acceptance deadlines",
                    path=f"restore.{application_id}.deadline_at",
                )
                for application_id in open_deadlines
            ]
        )

    operations: list[StateOp] = [
        StateOp(
            op="update",
            model="offers",
            values={
                "terminated_at": state.now,
                "terminated_by": actor.user_id,
                "termination_kind": input_value.termination_kind.value,
                "termination_reason": input_value.reason,
            },
            where={"id": input_value.offer_id},
        ),
        StateOp(
            op="update",
            model="applications",
            values={"status": ApplicationStatus.OFFER_TERMINATED.value},
            where={"id": input_value.application_id},
        ),
    ]
    events: list[Event] = [
        Event(
            application_id=input_value.application_id,
            event_type=EventType.OFFER_TERMINATED,
            from_status=target.status.value,
            to_status=ApplicationStatus.OFFER_TERMINATED.value,
            from_round=target.current_round_id,
            to_round=target.current_round_id,
            reason=input_value.reason,
            payload={
                "offer_id": str(input_value.offer_id),
                "termination_kind": input_value.termination_kind.value,
                "restored_application_ids": [
                    str(item) for item in sorted(selected, key=lambda value: value.int)
                ],
            },
        )
    ]
    deferred: list[Deferred] = []
    restored: list[dict[str, object]] = []
    for application_id in sorted(selected, key=lambda item: item.int):
        candidate = by_candidate[application_id]
        application = by_application[application_id]
        choice = selected[application_id]
        if candidate.requires_fresh_offer:
            fresh_offer_id, extension = plan_extension(
                application,
                now=state.now,
                deadline=choice.deadline_at,
                notify=input_value.notify,
            )
            operations.extend(extension.state_ops)
            events.extend(extension.events)
            deferred.extend(extension.deferred)
            restored.append(
                {
                    "application_id": str(application_id),
                    "status": ApplicationStatus.OFFERED.value,
                    "target_round_id": (
                        str(candidate.restore_round_id)
                        if candidate.restore_round_id
                        else None
                    ),
                    "fresh_offer_id": str(fresh_offer_id),
                    "deadline_at": (
                        choice.deadline_at.isoformat() if choice.deadline_at else None
                    ),
                }
            )
        else:
            operations.append(
                StateOp(
                    op="update",
                    model="applications",
                    values={
                        "status": candidate.restore_status.value,
                        "current_round_id": candidate.restore_round_id,
                    },
                    where={"id": application_id},
                )
            )
            events.append(
                Event(
                    application_id=application_id,
                    event_type=EventType.REINSTATED,
                    from_status=candidate.current_status.value,
                    to_status=candidate.restore_status.value,
                    from_round=application.current_round_id,
                    to_round=candidate.restore_round_id,
                    reason=input_value.reason,
                    payload={
                        "trigger": "offer_termination_restore",
                        "terminated_offer_id": str(input_value.offer_id),
                    },
                )
            )
            restored.append(
                {
                    "application_id": str(application_id),
                    "status": candidate.restore_status.value,
                    "target_round_id": (
                        str(candidate.restore_round_id)
                        if candidate.restore_round_id
                        else None
                    ),
                    "fresh_offer_id": None,
                    "deadline_at": None,
                }
            )

    discipline_summary: dict[str, object] | None = None
    if input_value.discipline is not None:
        if state.discipline is None:
            raise RuntimeError("The accepted offer's enrollment has no discipline row")
        # This reason is stored on the strike or penalty and is read back to
        # the student verbatim, so the enum does not travel into the middle of
        # the sentence: "Offer terminated (student renege): ..." rather than
        # "Offer student_renege: ...".
        discipline_reason = (
            f"Offer terminated ({humanise(input_value.termination_kind.value).lower()}): "
            f"{input_value.reason}"
        )
        if input_value.discipline == "strike":
            outcome = award_strikes(
                [
                    StrikeIntent(
                        enrollment_id=target.enrollment_id,
                        reason=discipline_reason,
                        source=StrikeSource.MANUAL,
                    )
                ],
                {target.enrollment_id: state.discipline},
                threshold=state.threshold,
                now=state.now,
                actor_user_id=actor.user_id,
            )
            reported = outcome.rows[0]
            discipline_summary = {
                "kind": "strike",
                "strike_total": reported["strike_total"],
                "penalties_created": reported["penalties_created"],
            }
        else:
            outcome = award_direct_penalty(
                state.discipline,
                reasons=discipline_reason,
                actor_user_id=actor.user_id,
            )
            discipline_summary = {"kind": "penalty", "penalty_active": True}
        operations.extend(outcome.state_ops)
        deferred.extend(outcome.deferred)

    if input_value.notify:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "offer_terminated",
                    "recipient": target.email,
                    "context": {
                        "student": target.full_name,
                        "job": target.job_title,
                        "company": target.company_name,
                        "kind": humanise(input_value.termination_kind.value),
                        "reason": input_value.reason,
                        "cycle_id": str(target.cycle_id),
                    },
                },
            )
        )

    candidate_payloads = [
        _candidate_payload(
            candidate,
            by_application[candidate.application_id],
            selected=selected.get(candidate.application_id),
            duplicate_application=duplicate_by_id[candidate.application_id],
        )
        for candidate in candidates
    ]
    automatic_effects: list[dict[str, object]] = [
        {
            "effect": "offer_terminated",
            "offer_id": str(input_value.offer_id),
            "kind": input_value.termination_kind.value,
        },
        {
            "effect": "application_transition",
            "application_id": str(input_value.application_id),
            "from_status": target.status.value,
            "to_status": ApplicationStatus.OFFER_TERMINATED.value,
        },
        {
            "effect": "placed_dimensions_rederived",
            "enrollment_id": str(target.enrollment_id),
        },
        {
            "effect": "cycle_cap_released",
            "cycle_id": str(target.cycle_id),
            "applies": target.status is ApplicationStatus.ACCEPTED,
        },
    ]
    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit={
            "subject_type": "application",
            "subject_id": input_value.application_id,
            "details": {
                "operation": "terminate_offer",
                "offer_id": str(input_value.offer_id),
                "termination_kind": input_value.termination_kind.value,
                "reason": input_value.reason,
                "restored_application_ids": [
                    str(item) for item in sorted(selected, key=lambda value: value.int)
                ],
                "discipline": input_value.discipline,
                "notify": input_value.notify,
            },
        },
        summary={
            "cycle_id": str(input_value.cycle_id),
            "job_id": str(input_value.job_id),
            "application_id": str(input_value.application_id),
            "offer_id": str(input_value.offer_id),
            "enrollment_id": str(target.enrollment_id),
            "status": ApplicationStatus.OFFER_TERMINATED.value,
            "termination_kind": input_value.termination_kind.value,
            "reason": input_value.reason,
            "automatic_effects": automatic_effects,
            "restoration_candidates": candidate_payloads,
            "restored": restored,
            "discipline": discipline_summary,
            "notify": input_value.notify,
        },
    )


def _decide_re_extend(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """OFR-5/APP-4.16: a fresh row after decline or termination."""
    if not isinstance(input_value, ReExtendOfferInput) or not isinstance(
        state, OfferInterventionState
    ):
        raise TypeError("Invalid re_extend_offer decision input")
    reasons = _target_reasons(
        cycle=state.cycle,
        job=state.job,
        target=state.target,
        offer_id=input_value.offer_id,
        expected_status=input_value.expected_status,
    )
    if reasons:
        return Rejection(reasons=reasons)
    assert state.cycle is not None and state.target is not None
    target = state.target
    if target.status not in {
        ApplicationStatus.DECLINED,
        ApplicationStatus.OFFER_TERMINATED,
    }:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Only a declined or terminated offer can be re-extended",
                    path="expected_status",
                )
            ]
        )
    if target.status is ApplicationStatus.DECLINED and (
        target.current_offer_response is None or target.current_offer_terminated
    ):
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human="The declined application no longer has a current declined offer",
                )
            ]
        )
    if (
        target.status is ApplicationStatus.OFFER_TERMINATED
        and not target.current_offer_terminated
    ):
        return Rejection(
            reasons=[
                Reason(
                    code=STALE_VIEW,
                    human="The terminated application no longer has a terminated current offer",
                )
            ]
        )
    if target.cycle_kind is CycleKind.OPEN and input_value.deadline_at is not None:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human="Open-cycle offers do not carry acceptance deadlines",
                    path="deadline_at",
                )
            ]
        )
    transition = decide_transition(
        "re_extend",
        from_status=target.status,
        to_status=ApplicationStatus.OFFERED,
        actor=TransitionActor.STAFF,
        context=TransitionContext(cycle_kind=target.cycle_kind),
    )
    if isinstance(transition, Rejection):
        return transition
    fresh_offer_id, extension = plan_extension(
        target,
        now=state.now,
        deadline=input_value.deadline_at,
        notify=input_value.notify,
    )
    return Plan(
        state_ops=list(extension.state_ops),
        events=list(extension.events),
        deferred=list(extension.deferred),
        audit={
            "subject_type": "application",
            "subject_id": input_value.application_id,
            "details": {
                "operation": "re_extend_offer",
                "previous_offer_id": str(input_value.offer_id),
                "offer_id": str(fresh_offer_id),
                "reason": input_value.reason,
                "deadline_at": (
                    input_value.deadline_at.isoformat()
                    if input_value.deadline_at
                    else None
                ),
                "notify": input_value.notify,
            },
        },
        summary={
            "cycle_id": str(input_value.cycle_id),
            "job_id": str(input_value.job_id),
            "application_id": str(input_value.application_id),
            "previous_offer_id": str(input_value.offer_id),
            "offer_id": str(fresh_offer_id),
            "enrollment_id": str(target.enrollment_id),
            "status": ApplicationStatus.OFFERED.value,
            "deadline_at": (
                input_value.deadline_at.isoformat() if input_value.deadline_at else None
            ),
            "notify": input_value.notify,
        },
    )


def register_termination_commands(registry: Registry) -> None:
    registry.command(
        name="terminate_offer",
        input_model=TerminateOfferInput,
        output_model=TerminateOfferSummary,
        actor="staff",
        scope="cycle",
        loader=_load_terminate,
        rule_domains=(),
        spec_ids=("OFR-5", "APP-4", "DER-1", "DIS"),
        rate_limit="10/min",
    )(_decide_terminate)
    registry.command(
        name="re_extend_offer",
        input_model=ReExtendOfferInput,
        output_model=ReExtendOfferSummary,
        actor="staff",
        scope="cycle",
        loader=_load_re_extend,
        rule_domains=(),
        spec_ids=("OFR-1", "OFR-2", "OFR-5", "APP-4"),
        rate_limit="10/min",
    )(_decide_re_extend)
