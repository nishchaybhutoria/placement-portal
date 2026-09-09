"""Pure plan fragments shared by every portal-offer command path."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

from app.core.plan import Deferred, Event, StateOp
from app.domain.shared import (
    ApplicationStatus,
    CycleKind,
    EventType,
    OfferResponse,
    Outcome,
)
from app.domain.transitions import ApplicationOfferState, compute_acceptance_cascade
from app.modules.notifications.wording import format_deadline, withdrawal_trigger


@dataclass(frozen=True, slots=True)
class OfferApplication:
    application_id: UUID
    enrollment_id: UUID
    status: ApplicationStatus
    current_round_id: UUID | None
    job_id: UUID
    job_title: str
    company_name: str
    cycle_id: UUID
    cycle_name: str
    cycle_kind: CycleKind
    outcome: Outcome
    email: str
    full_name: str
    roll_number: str | None
    current_offer_id: UUID | None
    current_offer_deadline: datetime | None
    current_offer_response: OfferResponse | None
    current_offer_terminated: bool
    offer_count: int

    def transition_state(self) -> ApplicationOfferState:
        return ApplicationOfferState(
            application_id=self.application_id,
            status=self.status,
            outcome=self.outcome,
            cycle_id=self.cycle_id,
            cycle_kind=self.cycle_kind,
            current_round_id=self.current_round_id,
            current_offer_id=self.current_offer_id,
        )


@dataclass(frozen=True, slots=True)
class PlannedMutation:
    state_ops: tuple[StateOp, ...]
    events: tuple[Event, ...]
    deferred: tuple[Deferred, ...]


@dataclass(frozen=True, slots=True)
class PlannedAcceptance(PlannedMutation):
    cascade: tuple[dict[str, object], ...]


def offer_id_for(application_id: UUID, prior_count: int) -> UUID:
    """A preview-stable fresh row ID; history count distinguishes extensions."""
    return uuid5(NAMESPACE_URL, f"cds:offer:{application_id}:{prior_count}")


def plan_extension(
    application: OfferApplication,
    *,
    now: datetime,
    deadline: datetime | None,
    notify: bool,
) -> tuple[UUID, PlannedMutation]:
    offer_id = offer_id_for(application.application_id, application.offer_count)
    deferred: list[Deferred] = []
    if notify:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "offer_extended",
                    "recipient": application.email,
                    "context": {
                        "student": application.full_name,
                        "job": application.job_title,
                        "company": application.company_name,
                        "deadline": format_deadline(deadline),
                        "cycle_id": str(application.cycle_id),
                    },
                },
            )
        )
    if deadline is not None and application.cycle_kind is not CycleKind.OPEN:
        deferred.append(
            Deferred(
                task="enforce_offer_expiry",
                args={
                    "offer_id": str(offer_id),
                    "scheduled_deadline": deadline.isoformat(),
                },
                schedule_at=deadline,
            )
        )
    return (
        offer_id,
        PlannedMutation(
            state_ops=(
                StateOp(
                    op="insert",
                    model="offers",
                    values={
                        "id": offer_id,
                        "application_id": application.application_id,
                        "extended_at": now,
                        "deadline_at": deadline,
                    },
                ),
                StateOp(
                    op="update",
                    model="applications",
                    values={"status": ApplicationStatus.OFFERED.value},
                    where={"id": application.application_id},
                ),
            ),
            events=(
                Event(
                    application_id=application.application_id,
                    event_type=EventType.OFFER_EXTENDED,
                    from_status=application.status.value,
                    to_status=ApplicationStatus.OFFERED.value,
                    from_round=application.current_round_id,
                    to_round=application.current_round_id,
                    reason=None,
                    payload={
                        "offer_id": str(offer_id),
                        "job_id": str(application.job_id),
                        "cycle_id": str(application.cycle_id),
                        "deadline_at": deadline.isoformat() if deadline else None,
                    },
                ),
            ),
            deferred=tuple(deferred),
        ),
    )


def plan_acceptance(
    accepted: OfferApplication,
    applications: tuple[OfferApplication, ...],
    *,
    offer_id: UUID,
    now: datetime,
    applied_override_ids: tuple[UUID, ...],
    system_initiated: bool = False,
) -> PlannedAcceptance:
    """OFR-3's accepted row, event, and always-on cascade in exact order."""
    actions = compute_acceptance_cascade(
        accepted.transition_state(),
        tuple(application.transition_state() for application in applications),
        acceptance_offer_id=offer_id,
    )
    by_id = {application.application_id: application for application in applications}
    operations: list[StateOp] = [
        StateOp(
            op="update",
            model="offers",
            values={
                "response": OfferResponse.ACCEPTED.value,
                "responded_at": now,
            },
            where={"id": offer_id},
        ),
        StateOp(
            op="update",
            model="applications",
            values={"status": ApplicationStatus.ACCEPTED.value},
            where={"id": accepted.application_id},
        ),
    ]
    accepted_payload: dict[str, object] = {
        "offer_id": str(offer_id),
        "job_id": str(accepted.job_id),
        "cycle_id": str(accepted.cycle_id),
        "applied_override_ids": [str(item) for item in applied_override_ids],
    }
    if system_initiated:
        accepted_payload["system_initiated"] = True
    events: list[Event] = [
        Event(
            application_id=accepted.application_id,
            event_type=EventType.ACCEPTED,
            from_status=accepted.status.value,
            to_status=ApplicationStatus.ACCEPTED.value,
            from_round=accepted.current_round_id,
            to_round=accepted.current_round_id,
            reason=None,
            payload=accepted_payload,
        )
    ]
    deferred: list[Deferred] = [
        Deferred(
            task="deliver_notification",
            args={
                "event_key": "offer_accepted",
                "recipient": accepted.email,
                "context": {
                    "student": accepted.full_name,
                    "job": accepted.job_title,
                    "company": accepted.company_name,
                    "cycle_id": str(accepted.cycle_id),
                },
            },
        )
    ]
    cascade: list[dict[str, object]] = []
    for action in actions:
        target = by_id[action.application_id]
        if action.offer_id is not None:
            operations.append(
                StateOp(
                    op="update",
                    model="offers",
                    values={
                        "response": OfferResponse.DECLINED.value,
                        "responded_at": now,
                    },
                    where={"id": action.offer_id},
                )
            )
        operations.append(
            StateOp(
                op="update",
                model="applications",
                values={"status": action.to_status.value},
                where={"id": action.application_id},
            )
        )
        cascade_payload = dict(action.payload)
        if system_initiated:
            cascade_payload["system_initiated"] = True
        events.append(
            Event(
                application_id=action.application_id,
                event_type=action.event_type,
                from_status=action.from_status.value,
                to_status=action.to_status.value,
                from_round=action.from_round_id,
                to_round=action.from_round_id,
                reason="Accepted another offer",
                payload=cascade_payload,
            )
        )
        event_key = (
            "auto_declined" if action.to_status is ApplicationStatus.DECLINED else "auto_withdrawn"
        )
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": event_key,
                    "recipient": target.email,
                    "context": {
                        "student": target.full_name,
                        "job": target.job_title,
                        "company": target.company_name,
                        "accepted_job": accepted.job_title,
                        "trigger": withdrawal_trigger("accepted_another_offer"),
                        "cycle_id": str(target.cycle_id),
                    },
                },
            )
        )
        cascade.append(
            {
                "application_id": str(action.application_id),
                "job_id": str(target.job_id),
                "job": target.job_title,
                "company": target.company_name,
                "cycle_id": str(target.cycle_id),
                "cycle": target.cycle_name,
                "from_status": action.from_status.value,
                "to_status": action.to_status.value,
                "event_type": action.event_type.value,
            }
        )

    return PlannedAcceptance(
        state_ops=tuple(operations),
        events=tuple(events),
        deferred=tuple(deferred),
        cascade=tuple(cascade),
    )


def plan_acceptance_cascade(
    accepted: OfferApplication,
    applications: tuple[OfferApplication, ...],
    *,
    acceptance_id: UUID,
    now: datetime,
) -> PlannedAcceptance:
    """The source-independent OFR-3 cascade used by external acceptance.

    ``plan_acceptance`` owns both the portal row and this cascade.  An external
    offer has no accepted application row, so this adapter deliberately removes
    that planner's first two state operations, first event, and first deferred
    notification while retaining the exact cascade it computed.  Keeping the
    computation here means portal and external paths cannot drift in scoping,
    causal payloads, event types, or notices.
    """
    planned = plan_acceptance(
        accepted,
        applications,
        offer_id=acceptance_id,
        now=now,
        applied_override_ids=(),
    )
    return PlannedAcceptance(
        state_ops=planned.state_ops[2:],
        events=planned.events[1:],
        deferred=planned.deferred[1:],
        cascade=planned.cascade,
    )


def plan_decline(
    application: OfferApplication,
    *,
    offer_id: UUID,
    now: datetime,
    event_key: str = "declined_confirm",
    reason: str | None = None,
    system_initiated: bool = False,
    payload_extra: dict[str, object] | None = None,
    notification_context_extra: dict[str, object] | None = None,
) -> PlannedMutation:
    return PlannedMutation(
        state_ops=(
            StateOp(
                op="update",
                model="offers",
                values={
                    "response": OfferResponse.DECLINED.value,
                    "responded_at": now,
                },
                where={"id": offer_id},
            ),
            StateOp(
                op="update",
                model="applications",
                values={"status": ApplicationStatus.DECLINED.value},
                where={"id": application.application_id},
            ),
        ),
        events=(
            Event(
                application_id=application.application_id,
                event_type=EventType.DECLINED,
                from_status=application.status.value,
                to_status=ApplicationStatus.DECLINED.value,
                from_round=application.current_round_id,
                to_round=application.current_round_id,
                reason=reason,
                payload={
                    "offer_id": str(offer_id),
                    "job_id": str(application.job_id),
                    "cycle_id": str(application.cycle_id),
                    **({"system_initiated": True} if system_initiated else {}),
                    **(payload_extra or {}),
                },
            ),
        ),
        deferred=(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": event_key,
                    "recipient": application.email,
                    "context": {
                        "student": application.full_name,
                        "job": application.job_title,
                        "company": application.company_name,
                        "cycle_id": str(application.cycle_id),
                        **(notification_context_extra or {}),
                    },
                },
            ),
        ),
    )
