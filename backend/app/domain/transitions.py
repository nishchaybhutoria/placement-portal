"""Declarative APP-4 transitions and pure OFR/RND decision helpers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.core.errors import INVALID_TRANSITION
from app.core.plan import Reason, Rejection
from app.domain.shared import (
    ApplicationStatus,
    Attendance,
    CycleKind,
    EventType,
    OfferExpiry,
    OfferResponse,
    Outcome,
    RoundResult,
)


class TransitionActor(StrEnum):
    STUDENT = "student"
    STAFF = "staff"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class TransitionSpec:
    name: str
    from_statuses: tuple[ApplicationStatus | None, ...]
    to_status: ApplicationStatus | Literal["any_other"]
    actors: tuple[TransitionActor, ...]
    requires_reason: bool
    in_tx_effects: tuple[str, ...]
    deferred_effects: tuple[str, ...]
    spec: str

    def decide(
        self,
        *,
        from_status: ApplicationStatus | None,
        to_status: ApplicationStatus,
        actor: TransitionActor,
        context: TransitionContext,
        reason: str | None = None,
    ) -> TransitionSpec | Rejection:
        """Run this table row's pure legality and reason checks."""
        legal_names = legal_transition_names(
            from_status,
            to_status,
            actor,
            context,
            include_force=self.name == "force",
        )
        if self.name not in legal_names:
            return _invalid_transition("The requested status transition is not legal")
        if self.requires_reason and (reason is None or not reason.strip()):
            return _invalid_transition("This status transition requires a reason")
        return self


TRANSITIONS: tuple[TransitionSpec, ...] = (
    TransitionSpec(
        "apply",
        (None,),
        ApplicationStatus.IN_PROGRESS,
        (TransitionActor.STUDENT,),
        False,
        ("snapshot", "round_1_state", "event:created"),
        ("notify:application_submitted",),
        "APP-4.1",
    ),
    TransitionSpec(
        "advance",
        (ApplicationStatus.IN_PROGRESS,),
        ApplicationStatus.IN_PROGRESS,
        (TransitionActor.STAFF,),
        False,
        ("round:advanced", "next_round:pending", "event:advanced"),
        ("notify:advanced",),
        "APP-4.2",
    ),
    TransitionSpec(
        "advance_final",
        (ApplicationStatus.IN_PROGRESS,),
        ApplicationStatus.PENDING_OFFER,
        (TransitionActor.STAFF,),
        False,
        ("round:advanced", "event:advanced"),
        (),
        "APP-4.3",
    ),
    TransitionSpec(
        "eliminate",
        (ApplicationStatus.IN_PROGRESS,),
        ApplicationStatus.REJECTED,
        (TransitionActor.STAFF,),
        True,
        ("round:eliminated", "event:eliminated"),
        ("notify:rejected",),
        "APP-4.4",
    ),
    TransitionSpec(
        "bulk_reject",
        (ApplicationStatus.IN_PROGRESS, ApplicationStatus.PENDING_OFFER),
        ApplicationStatus.REJECTED,
        (TransitionActor.STAFF,),
        True,
        ("event:eliminated",),
        ("notify:rejected",),
        "APP-4.4/5",
    ),
    TransitionSpec(
        "cancel_job",
        (
            ApplicationStatus.IN_PROGRESS,
            ApplicationStatus.PENDING_OFFER,
            ApplicationStatus.OFFERED,
        ),
        ApplicationStatus.REJECTED,
        (TransitionActor.STAFF,),
        True,
        ("terminate_open_offer", "event:eliminated"),
        ("notify:job_cancelled",),
        "APP-4.4/5",
    ),
    TransitionSpec(
        "extend_offer",
        (ApplicationStatus.IN_PROGRESS, ApplicationStatus.PENDING_OFFER),
        ApplicationStatus.OFFERED,
        (TransitionActor.STAFF,),
        False,
        ("offer:create", "event:offer_extended"),
        ("notify:offer_extended", "schedule:offer_expiry"),
        "APP-4.6/7",
    ),
    TransitionSpec(
        "accept",
        (ApplicationStatus.OFFERED,),
        ApplicationStatus.ACCEPTED,
        (TransitionActor.STUDENT, TransitionActor.STAFF, TransitionActor.SYSTEM),
        False,
        ("offer:accept", "acceptance_cascade", "event:accepted"),
        ("notify:accepted", "notify:cascade"),
        "APP-4.8",
    ),
    TransitionSpec(
        "decline",
        (ApplicationStatus.OFFERED,),
        ApplicationStatus.DECLINED,
        (TransitionActor.STUDENT, TransitionActor.STAFF, TransitionActor.SYSTEM),
        False,
        ("offer:decline", "event:declined"),
        ("notify:declined",),
        "APP-4.9",
    ),
    TransitionSpec(
        "withdraw",
        (ApplicationStatus.IN_PROGRESS,),
        ApplicationStatus.WITHDRAWN,
        (TransitionActor.STUDENT,),
        False,
        ("event:withdrawn",),
        (),
        "APP-4.12",
    ),
    TransitionSpec(
        "auto_withdraw",
        (ApplicationStatus.IN_PROGRESS, ApplicationStatus.PENDING_OFFER),
        ApplicationStatus.AUTO_WITHDRAWN,
        (TransitionActor.SYSTEM,),
        False,
        ("event:auto_withdrawn",),
        ("notify:auto_withdrawn",),
        "APP-4.13",
    ),
    TransitionSpec(
        "terminate_offer",
        (ApplicationStatus.OFFERED, ApplicationStatus.ACCEPTED),
        ApplicationStatus.OFFER_TERMINATED,
        (TransitionActor.STAFF,),
        True,
        ("offer:terminate", "restore:selected", "event:offer_terminated"),
        ("notify:optional",),
        "APP-4.10/11",
    ),
    TransitionSpec(
        "reinstate",
        (
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.AUTO_WITHDRAWN,
        ),
        ApplicationStatus.IN_PROGRESS,
        (TransitionActor.STAFF,),
        True,
        ("rounds:reset", "event:reinstated"),
        ("notify:optional",),
        "APP-4.14",
    ),
    TransitionSpec(
        "direct_offer",
        tuple(
            status
            for status in ApplicationStatus
            if status not in {ApplicationStatus.ACCEPTED, ApplicationStatus.OFFERED}
        ),
        ApplicationStatus.OFFERED,
        (TransitionActor.STAFF,),
        False,
        ("offer:create", "event:offer_extended"),
        ("notify:offer_extended", "schedule:offer_expiry"),
        "APP-4.15",
    ),
    TransitionSpec(
        "re_extend",
        (ApplicationStatus.DECLINED, ApplicationStatus.OFFER_TERMINATED),
        ApplicationStatus.OFFERED,
        (TransitionActor.STAFF,),
        False,
        ("offer:create", "event:offer_extended"),
        ("notify:offer_extended", "schedule:offer_expiry"),
        "APP-4.16",
    ),
    TransitionSpec(
        "force",
        tuple(ApplicationStatus),
        "any_other",
        (TransitionActor.STAFF,),
        True,
        ("event:forced_transition", "implicit_consequences:none"),
        ("notify:optional",),
        "APP-4.17",
    ),
)


@dataclass(frozen=True, slots=True)
class TransitionContext:
    cycle_kind: CycleKind
    offer_expiry_behavior: OfferExpiry = OfferExpiry.AUTO_DECLINE


def legal_transition_names(
    from_status: ApplicationStatus | None,
    to_status: ApplicationStatus,
    actor: TransitionActor,
    context: TransitionContext,
    *,
    include_force: bool = False,
) -> tuple[str, ...]:
    """Return named APP-4 rows legal for a status/actor/context tuple."""
    names: list[str] = []
    for transition in TRANSITIONS:
        if transition.name == "force" and not include_force:
            continue
        to_matches = (
            transition.to_status is to_status
            if transition.to_status != "any_other"
            else from_status is not None and from_status is not to_status
        )
        if (
            from_status in transition.from_statuses
            and to_matches
            and actor in transition.actors
            and _actor_context_allows(transition.name, actor, context)
        ):
            names.append(transition.name)
    return tuple(names)


def decide_transition(
    name: str,
    *,
    from_status: ApplicationStatus | None,
    to_status: ApplicationStatus,
    actor: TransitionActor,
    context: TransitionContext,
    reason: str | None = None,
) -> TransitionSpec | Rejection:
    """Validate one named APP-4 decision against the declarative table."""
    transition = next((item for item in TRANSITIONS if item.name == name), None)
    if transition is None:
        return _invalid_transition("The requested status transition is not legal")
    return transition.decide(
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        context=context,
        reason=reason,
    )


def _invalid_transition(human: str) -> Rejection:
    return Rejection(reasons=[Reason(code=INVALID_TRANSITION, human=human, path="status")])


def _actor_context_allows(name: str, actor: TransitionActor, context: TransitionContext) -> bool:
    if name == "accept":
        if actor is TransitionActor.STUDENT:
            return context.cycle_kind is not CycleKind.OPEN
        if actor is TransitionActor.STAFF:
            return context.cycle_kind is CycleKind.OPEN
        return (
            context.cycle_kind is not CycleKind.OPEN
            and context.offer_expiry_behavior is OfferExpiry.AUTO_ACCEPT
        )
    if name == "decline":
        if actor is TransitionActor.STUDENT:
            return context.cycle_kind is not CycleKind.OPEN
        if actor is TransitionActor.STAFF:
            return context.cycle_kind is CycleKind.OPEN
        return context.cycle_kind is not CycleKind.OPEN
    return True


@dataclass(frozen=True, slots=True)
class ApplicationOfferState:
    application_id: UUID
    status: ApplicationStatus
    outcome: Outcome
    cycle_id: UUID
    cycle_kind: CycleKind
    current_round_id: UUID | None = None
    current_offer_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class CascadeAction:
    application_id: UUID
    offer_id: UUID | None
    from_status: ApplicationStatus
    to_status: ApplicationStatus
    from_round_id: UUID | None
    event_type: EventType
    payload: dict[str, object]


def compute_acceptance_cascade(
    accepted: ApplicationOfferState,
    others: tuple[ApplicationOfferState, ...],
    *,
    acceptance_offer_id: UUID,
) -> tuple[CascadeAction, ...]:
    """Compute the always-on OFR-3 cascade over a loader-provided snapshot."""
    if accepted.outcome is Outcome.INTERNSHIP and accepted.cycle_kind is CycleKind.OPEN:
        return ()

    actions: list[CascadeAction] = []
    for other in sorted(others, key=lambda item: item.application_id.int):
        if other.application_id == accepted.application_id or other.outcome is not accepted.outcome:
            continue
        if accepted.outcome is Outcome.INTERNSHIP and other.cycle_id != accepted.cycle_id:
            continue
        payload: dict[str, object] = {
            "trigger": "acceptance",
            "acceptance_offer_id": str(acceptance_offer_id),
            "accepted_application_id": str(accepted.application_id),
        }
        if other.status is ApplicationStatus.OFFERED:
            actions.append(
                CascadeAction(
                    application_id=other.application_id,
                    offer_id=other.current_offer_id,
                    from_status=other.status,
                    to_status=ApplicationStatus.DECLINED,
                    from_round_id=other.current_round_id,
                    event_type=EventType.AUTO_DECLINED,
                    payload=payload,
                )
            )
        elif other.status in {
            ApplicationStatus.IN_PROGRESS,
            ApplicationStatus.PENDING_OFFER,
        }:
            actions.append(
                CascadeAction(
                    application_id=other.application_id,
                    offer_id=None,
                    from_status=other.status,
                    to_status=ApplicationStatus.AUTO_WITHDRAWN,
                    from_round_id=other.current_round_id,
                    event_type=EventType.AUTO_WITHDRAWN,
                    payload=payload,
                )
            )
    return tuple(actions)


@dataclass(frozen=True, slots=True)
class EventHistoryItem:
    sequence: int
    application_id: UUID
    event_type: EventType
    from_status: ApplicationStatus | None
    to_status: ApplicationStatus | None
    from_round_id: UUID | None
    to_round_id: UUID | None
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class RestoreCandidate:
    application_id: UUID
    current_status: ApplicationStatus
    restore_status: ApplicationStatus
    restore_round_id: UUID | None
    requires_fresh_offer: bool


def compute_restore_candidates(
    *,
    acceptance_offer_id: UUID,
    history: tuple[EventHistoryItem, ...],
    current_statuses: dict[UUID, ApplicationStatus],
) -> tuple[RestoreCandidate, ...]:
    """Reconstruct OFR-5 choices caused by one acceptance without guessing."""
    causal = str(acceptance_offer_id)
    latest: dict[UUID, EventHistoryItem] = {}
    for event in history:
        if event.payload.get("acceptance_offer_id") != causal:
            continue
        if event.event_type not in {EventType.AUTO_DECLINED, EventType.AUTO_WITHDRAWN}:
            continue
        previous = latest.get(event.application_id)
        if previous is None or event.sequence > previous.sequence:
            latest[event.application_id] = event

    candidates: list[RestoreCandidate] = []
    for application_id, event in sorted(latest.items(), key=lambda item: item[0].int):
        current = current_statuses.get(application_id)
        if current is None or current is not event.to_status or event.from_status is None:
            continue
        if event.event_type is EventType.AUTO_DECLINED:
            restore_status = ApplicationStatus.OFFERED
            fresh_offer = True
        else:
            restore_status = event.from_status
            fresh_offer = False
        candidates.append(
            RestoreCandidate(
                application_id=application_id,
                current_status=current,
                restore_status=restore_status,
                restore_round_id=event.from_round_id,
                requires_fresh_offer=fresh_offer,
            )
        )
    return tuple(candidates)


class ExpiryAction(StrEnum):
    NOOP = "noop"
    RESCHEDULE = "reschedule"
    AUTO_DECLINE = "auto_decline"
    AUTO_ACCEPT = "auto_accept"
    AUTO_DECLINE_GATE_FALLBACK = "auto_decline_gate_fallback"


@dataclass(frozen=True, slots=True)
class ConsistencyFindingIntent:
    invariant: str
    subject: dict[str, object]
    detail: str


@dataclass(frozen=True, slots=True)
class ExpiryState:
    offer_id: UUID
    application_id: UUID
    application_status: ApplicationStatus
    is_latest_offer: bool
    response: OfferResponse | None
    terminated: bool
    deadline_at: datetime | None
    scheduled_deadline: datetime | None
    now: datetime
    cycle_kind: CycleKind
    behavior: OfferExpiry
    gate_failures: tuple[Reason, ...] = ()


@dataclass(frozen=True, slots=True)
class ExpiryDecision:
    action: ExpiryAction
    reschedule_at: datetime | None = None
    finding: ConsistencyFindingIntent | None = None


def decide_expiry(state: ExpiryState) -> ExpiryDecision:
    """Revalidate and decide OFR-4 without performing I/O."""
    if (
        state.cycle_kind is CycleKind.OPEN
        or not state.is_latest_offer
        or state.application_status is not ApplicationStatus.OFFERED
        or state.response is not None
        or state.terminated
        or state.deadline_at is None
    ):
        return ExpiryDecision(ExpiryAction.NOOP)
    if state.deadline_at != state.scheduled_deadline or state.now < state.deadline_at:
        return ExpiryDecision(ExpiryAction.RESCHEDULE, reschedule_at=state.deadline_at)
    if state.behavior is OfferExpiry.AUTO_DECLINE:
        return ExpiryDecision(ExpiryAction.AUTO_DECLINE)
    if not state.gate_failures:
        return ExpiryDecision(ExpiryAction.AUTO_ACCEPT)
    codes = ", ".join(failure.code for failure in state.gate_failures)
    return ExpiryDecision(
        ExpiryAction.AUTO_DECLINE_GATE_FALLBACK,
        finding=ConsistencyFindingIntent(
            invariant="offer_expiry_auto_accept_gate_failed",
            subject={
                "offer_id": str(state.offer_id),
                "application_id": str(state.application_id),
            },
            detail=f"Auto-accept fell back to decline because gates failed: {codes}",
        ),
    )


@dataclass(frozen=True, slots=True)
class RoundFinalizationState:
    application_id: UUID
    status: ApplicationStatus
    round_result: RoundResult
    attendance: Attendance


@dataclass(frozen=True, slots=True)
class RoundFinalizationAction:
    application_id: UUID
    attendance_after: Attendance
    result_after: RoundResult
    status_after: ApplicationStatus
    award_strike: bool
    reason: Literal["absence", "excused"]


def decide_round_finalization(
    rows: tuple[RoundFinalizationState, ...], *, strike_on_absence: bool
) -> tuple[RoundFinalizationAction, ...]:
    """Compute RND-3 absent/pending/excused effects; present rows stay untouched."""
    actions: list[RoundFinalizationAction] = []
    for row in sorted(rows, key=lambda item: item.application_id.int):
        if (
            row.status is not ApplicationStatus.IN_PROGRESS
            or row.round_result is not RoundResult.PENDING
            or row.attendance is Attendance.PRESENT
        ):
            continue
        if row.attendance in {Attendance.PENDING, Attendance.ABSENT}:
            actions.append(
                RoundFinalizationAction(
                    application_id=row.application_id,
                    attendance_after=Attendance.ABSENT,
                    result_after=RoundResult.ELIMINATED,
                    status_after=ApplicationStatus.REJECTED,
                    award_strike=strike_on_absence,
                    reason="absence",
                )
            )
        elif row.attendance is Attendance.EXCUSED:
            actions.append(
                RoundFinalizationAction(
                    application_id=row.application_id,
                    attendance_after=Attendance.EXCUSED,
                    result_after=RoundResult.ELIMINATED,
                    status_after=ApplicationStatus.REJECTED,
                    award_strike=False,
                    reason="excused",
                )
            )
    return tuple(actions)
