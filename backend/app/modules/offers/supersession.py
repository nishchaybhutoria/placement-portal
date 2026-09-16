"""Moving a student's single placement from one accepted offer to another.

`placement_placed` is derived, never stored (DER-1): a student is placed
because an accepted, unterminated placement offer exists, not because a column
says so.  That is the right model -- it cannot go stale -- but it means there
is no "final placement" pointer for an admin to repoint when the real answer
changes, and the answer does change.  ELG-3.6 now keeps open cycles open to
placed students, so the ordinary path to this command is a student who is
already placed, applies to a rolling role, and is chosen for it.

Doing that with the pieces that already exist means two commands in two
transactions: terminate the old offer, then accept the new one.  Between them
the student is un-placed, the two halves cascade separately, the old cycle may
be archived and refuse the termination entirely, a PPO needs a different
command from a portal offer, and the audit trail records two unrelated events
months apart with nothing saying they were one decision.

So this is one command.  It terminates and accepts under a single enrollment
mutex, computes one cascade against post-termination state, restores what the
old acceptance took away, and links the two halves in their event payloads so
the pair reads as one decision.  An external offer has no application row and
therefore no event of its own -- ``update_external_offer`` has the same gap --
so where a side is external the link is carried by the portal side alone, and
by the single audit row, which always names both.  The outcome gate is not
overridden here, it is simply not asked:
the command exists precisely to end one placement and begin another, and
exactly one accepted placement offer survives it -- so
``one_accepted_placement_offer_globally`` keeps holding without an authorised
double-acceptance carve-out.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    CYCLE_ARCHIVED,
    ENROLLMENT_NOT_FOUND,
    INVALID_TRANSITION,
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
from app.domain.gates import evaluate_offer_cap
from app.domain.policy import resolve_policy
from app.domain.shared import (
    ApplicationStatus,
    CycleKind,
    ExternalStatus,
    Outcome,
    RuleDomain,
    TerminationKind,
)
from app.domain.transitions import EventHistoryItem
from app.modules.applications.verdict import gate_overrides
from app.modules.cycles.commands import fetch_cycle, fetch_policy
from app.modules.offers.commands import _load_offer_applications
from app.modules.offers.derivations import offer_facts
from app.modules.offers.external import (
    EnrollmentRow,
    ExternalOfferRow,
    RestoreSelection,
    _acceptance_subject,
    _enrollment,
    _external_offer,
    _history,
    plan_restoration,
)
from app.modules.offers.locking import AcceptanceLockRequest, lock_acceptance_state
from app.modules.offers.planning import (
    OfferApplication,
    plan_acceptance,
    plan_acceptance_cascade,
    plan_termination,
)
from app.modules.overrides.service import ApplicableOverride

#: The termination kind a replacement always uses.  A renege is a disciplinary
#: judgement about the student and a revocation is a statement about the
#: company; neither describes the office correcting which offer counts.  Staff
#: who do want the renege review reach for ``terminate_offer``, which still
#: carries the strike and penalty choices.
REPLACEMENT_KIND = TerminationKind.ADMIN_CORRECTION


class ReplacePlacementInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enrollment_id: UUID
    #: The placement being ended.  Naming it is the compare-and-set: a stale
    #: screen sends the offer it could see, and a placement that moved in the
    #: meantime is a rejection rather than a silent termination of whatever
    #: happens to be accepted now.
    current_offer_id: UUID | None = None
    current_external_offer_id: UUID | None = None
    #: The placement being taken up.
    new_offer_id: UUID | None = None
    new_external_offer_id: UUID | None = None
    reason: str = Field(min_length=1)
    restore: list[RestoreSelection] = []
    notify: bool = True

    @model_validator(mode="after")
    def exactly_one_of_each_side(self) -> ReplacePlacementInput:
        if (self.current_offer_id is None) == (self.current_external_offer_id is None):
            raise ValueError(
                "name exactly one of current_offer_id or current_external_offer_id"
            )
        if (self.new_offer_id is None) == (self.new_external_offer_id is None):
            raise ValueError("name exactly one of new_offer_id or new_external_offer_id")
        if (
            self.current_offer_id is not None
            and self.current_offer_id == self.new_offer_id
        ) or (
            self.current_external_offer_id is not None
            and self.current_external_offer_id == self.new_external_offer_id
        ):
            raise ValueError("the outgoing and incoming placements must differ")
        return self


class ReplacePlacementSummary(BaseModel):
    enrollment_id: UUID
    from_placement: dict[str, object]
    to_placement: dict[str, object]
    cascade: list[dict[str, object]]
    restoration_candidates: list[dict[str, object]]
    restored: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class ReplacePlacementState:
    scope_ids: ScopeIds
    now: datetime
    enrollment: EnrollmentRow | None
    applications: tuple[OfferApplication, ...]
    outgoing_external: ExternalOfferRow | None
    incoming_external: ExternalOfferRow | None
    history: tuple[EventHistoryItem, ...]
    #: The cap on the cycle the *incoming* placement lands in, and how much of
    #: it is spent once the outgoing offer's slot is given back.
    incoming_cycle_id: UUID | None
    incoming_cycle_archived: bool
    max_accepted_offers: int | None
    cap_used: int


async def _load_replace(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ReplacePlacementState:
    if not isinstance(input_value, ReplacePlacementInput):
        raise TypeError("replace_placement requires ReplacePlacementInput")

    # One mutex for the whole operation.  Both halves touch the same
    # enrollment's placed state, so they take the documented cross-cycle,
    # cross-source lock once rather than racing each other's cap arithmetic.
    await lock_acceptance_state(
        tx,
        (
            AcceptanceLockRequest(
                enrollment_id=input_value.enrollment_id,
                cycle_id=None,
                application_id=None,
                outcome=Outcome.PLACEMENT,
                cycle_kind=None,
                external_offer_id=input_value.current_external_offer_id,
            ),
        ),
        lock=lock,
    )

    enrollment = await _enrollment(tx, input_value.enrollment_id)
    if enrollment is None:
        return ReplacePlacementState(
            scope_ids=ScopeIds(enrollment_id=input_value.enrollment_id),
            now=await _now(tx),
            enrollment=None,
            applications=(),
            outgoing_external=None,
            incoming_external=None,
            history=(),
            incoming_cycle_id=None,
            incoming_cycle_archived=False,
            max_accepted_offers=None,
            cap_used=0,
        )

    applications = await _load_offer_applications(
        tx, enrollment_ids=(input_value.enrollment_id,)
    )
    outgoing_external = (
        await _external_offer(tx, input_value.current_external_offer_id)
        if input_value.current_external_offer_id is not None
        else None
    )
    incoming_external = (
        await _external_offer(tx, input_value.new_external_offer_id)
        if input_value.new_external_offer_id is not None
        else None
    )

    incoming_cycle_id = _incoming_cycle_id(
        input_value, applications=applications, incoming_external=incoming_external
    )
    incoming_cycle_archived = False
    maximum: int | None = None
    cap_used = 0
    if incoming_cycle_id is not None:
        cycle = await fetch_cycle(tx, incoming_cycle_id, lock=False)
        incoming_cycle_archived = cycle is not None and cycle.archived_at is not None
        if cycle is not None:
            maximum = resolve_policy(
                CycleKind(cycle.kind),
                cycle_policy=await fetch_policy(tx, incoming_cycle_id),
            ).max_accepted_offers.value
        facts = await offer_facts(tx, input_value.enrollment_id, incoming_cycle_id)
        cap_used = facts.cap_used

    return ReplacePlacementState(
        scope_ids=ScopeIds(
            cycle_id=incoming_cycle_id, enrollment_id=input_value.enrollment_id
        ),
        now=await _now(tx),
        enrollment=enrollment,
        applications=applications,
        outgoing_external=outgoing_external,
        incoming_external=incoming_external,
        history=await _history(tx, input_value.enrollment_id),
        incoming_cycle_id=incoming_cycle_id,
        incoming_cycle_archived=incoming_cycle_archived,
        max_accepted_offers=maximum,
        cap_used=cap_used,
    )


async def _now(tx: AsyncSession) -> datetime:
    return cast(datetime, await tx.scalar(sa.select(sa.func.now())))


def _incoming_cycle_id(
    input_value: ReplacePlacementInput,
    *,
    applications: tuple[OfferApplication, ...],
    incoming_external: ExternalOfferRow | None,
) -> UUID | None:
    if input_value.new_external_offer_id is not None:
        # An unattached external offer consumes no cycle's cap (EXT-3).
        return incoming_external.attached_cycle_id if incoming_external else None
    target = _application_for_offer(applications, input_value.new_offer_id)
    return target.cycle_id if target else None


def _application_for_offer(
    applications: tuple[OfferApplication, ...], offer_id: UUID | None
) -> OfferApplication | None:
    if offer_id is None:
        return None
    return next(
        (row for row in applications if row.current_offer_id == offer_id), None
    )


def _outgoing_cycle_id(
    input_value: ReplacePlacementInput,
    *,
    applications: tuple[OfferApplication, ...],
    outgoing_external: ExternalOfferRow | None,
) -> UUID | None:
    if input_value.current_external_offer_id is not None:
        return outgoing_external.attached_cycle_id if outgoing_external else None
    target = _application_for_offer(applications, input_value.current_offer_id)
    return target.cycle_id if target else None


def _rejection(code: str, human: str, path: str | None = None) -> Rejection:
    return Rejection(reasons=[Reason(code=code, human=human, path=path)])


def _decide_replace_placement(
    input_value: BaseModel,
    state: object,
    _policy: object,
    overrides: object,
    actor: ActorContext,
) -> Plan | Rejection:
    """End one accepted placement and begin another, in one transaction."""
    if not isinstance(input_value, ReplacePlacementInput) or not isinstance(
        state, ReplacePlacementState
    ):
        raise TypeError("Invalid replace_placement decision input")
    if state.enrollment is None:
        return _rejection(
            ENROLLMENT_NOT_FOUND, "The enrollment does not exist", "enrollment_id"
        )

    outgoing = _validate_outgoing(input_value, state)
    if isinstance(outgoing, Rejection):
        return outgoing
    incoming = _validate_incoming(input_value, state)
    if isinstance(incoming, Rejection):
        return incoming

    # The outgoing offer's slot is released in this same transaction, so the
    # incoming one is measured against the cap it will actually meet rather
    # than against a count that includes the placement being replaced.
    outgoing_cycle_id = _outgoing_cycle_id(
        input_value,
        applications=state.applications,
        outgoing_external=state.outgoing_external,
    )
    releases_slot = (
        state.incoming_cycle_id is not None
        and outgoing_cycle_id == state.incoming_cycle_id
    )
    resolved = gate_overrides(cast("tuple[ApplicableOverride, ...]", overrides))
    cap = evaluate_offer_cap(
        max_accepted_offers=state.max_accepted_offers,
        cap_used=max(state.cap_used - (1 if releases_slot else 0), 0),
        overrides=resolved,
    )
    if cap.failures:
        return Rejection(reasons=list(cap.failures))

    outgoing_id = (
        input_value.current_offer_id
        if input_value.current_offer_id is not None
        else cast(UUID, input_value.current_external_offer_id)
    )

    operations: list[StateOp] = []
    events: list[Event] = []
    deferred: list[Deferred] = []

    # 1. End the outgoing placement, naming what replaces it.
    if isinstance(outgoing, OfferApplication):
        termination = plan_termination(
            outgoing,
            offer_id=cast(UUID, input_value.current_offer_id),
            now=state.now,
            actor_user_id=actor.user_id,
            termination_kind=REPLACEMENT_KIND,
            reason=input_value.reason,
            restored_application_ids=tuple(
                selection.application_id for selection in input_value.restore
            ),
            extra_payload=_supersession_payload(input_value, key="superseded_by"),
        )
        operations.extend(termination.state_ops)
        events.extend(termination.events)
        deferred.extend(termination.deferred)
    else:
        operations.append(
            StateOp(
                op="update",
                model="external_offers",
                values={
                    "status": ExternalStatus.DECLINED.value,
                    "responded_on": state.now.date(),
                },
                where={"id": outgoing.id},
            )
        )

    # 2. Put back what the outgoing acceptance took away, by explicit choice.
    restoration = plan_restoration(
        acceptance_id=outgoing_id,
        history=state.history,
        applications=state.applications,
        selections=input_value.restore,
        now=state.now,
        reason=input_value.reason,
        notify=input_value.notify,
        trigger="placement_replaced",
        source_field="superseded_offer_id",
    )
    if isinstance(restoration, Rejection):
        return restoration
    operations.extend(restoration.operations)
    events.extend(restoration.events)
    deferred.extend(restoration.deferred)

    # 3. Take up the incoming placement, cascading against the state this
    #    transaction has already produced: the offer just ended is no longer a
    #    competitor to decline, and a restored application is live again and
    #    must be judged as such rather than as the withdrawn row it was.
    restored_status = {
        UUID(str(item["application_id"])): ApplicationStatus(str(item["status"]))
        for item in restoration.restored
    }
    remaining = tuple(
        replace(row, status=restored_status[row.application_id])
        if row.application_id in restored_status
        else row
        for row in state.applications
        if not (
            isinstance(outgoing, OfferApplication)
            and row.application_id == outgoing.application_id
        )
    )
    supersedes = _supersession_payload(input_value, key="supersedes")
    if isinstance(incoming, OfferApplication):
        accepted = plan_acceptance(
            incoming,
            remaining,
            offer_id=cast(UUID, input_value.new_offer_id),
            now=state.now,
            applied_override_ids=cap.applied_override_ids,
        )
        events.extend(_with_payload(accepted.events[:1], supersedes))
        operations.extend(accepted.state_ops)
        events.extend(accepted.events[1:])
        cascade = accepted.cascade
    else:
        operations.append(
            StateOp(
                op="update",
                model="external_offers",
                values={
                    "status": ExternalStatus.ACCEPTED.value,
                    "responded_on": state.now.date(),
                },
                where={"id": incoming.id},
            )
        )
        accepted = plan_acceptance_cascade(
            _acceptance_subject(
                external_offer_id=incoming.id,
                enrollment=state.enrollment,
                company_name=incoming.company_name,
                outcome=incoming.outcome,
                attached_cycle_id=incoming.attached_cycle_id,
                attached_cycle_name=incoming.attached_cycle_name,
                attached_cycle_kind=incoming.attached_cycle_kind,
            ),
            remaining,
            acceptance_id=incoming.id,
            now=state.now,
        )
        operations.extend(accepted.state_ops)
        events.extend(accepted.events)
        cascade = accepted.cascade
    # The acceptance planner's own "you accepted an offer" notice is dropped:
    # a student who is being moved between placements should receive one
    # message describing the move, not a termination notice racing an
    # acceptance notice with nothing connecting them.
    deferred.extend(
        item for item in accepted.deferred if item.args.get("event_key") != "offer_accepted"
    )

    # Restoring an application the incoming acceptance would cascade straight
    # back out is not a choice, it is a round trip: the student is placed
    # before and after, so whatever the old acceptance moved aside for being a
    # competing placement is still competing. Say so rather than writing a
    # restore event and its undo into the same transaction. What survives is
    # what this acceptance does not reach -- an open-cycle application, or one
    # of the other outcome (ELG-3.6).
    undone = sorted(
        str(row["application_id"])
        for row in cascade
        if UUID(str(row["application_id"])) in restored_status
    )
    if undone:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_TRANSITION,
                    human=(
                        "This application cannot be restored here: the incoming "
                        "placement would withdraw it again immediately. Terminate "
                        "the placement instead if it should be released."
                    ),
                    path=f"restore.{application_id}",
                )
                for application_id in undone
            ]
        )

    from_placement = _placement_payload(outgoing)
    to_placement = _placement_payload(incoming)
    if input_value.notify:
        deferred.append(
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "placement_replaced",
                    "recipient": state.enrollment.email,
                    "context": {
                        "student": state.enrollment.full_name,
                        "from_job": from_placement["job"],
                        "from_company": from_placement["company"],
                        "to_job": to_placement["job"],
                        "to_company": to_placement["company"],
                        "reason": input_value.reason,
                    },
                },
            )
        )

    return Plan(
        state_ops=operations,
        events=events,
        deferred=deferred,
        audit={
            "subject_type": "enrollment",
            "subject_id": input_value.enrollment_id,
            "details": {
                "operation": "replace_placement",
                "from": from_placement,
                "to": to_placement,
                "reason": input_value.reason,
                "cascade_count": len(cascade),
                "restored_application_ids": [
                    str(item["application_id"]) for item in restoration.restored
                ],
                "applied_override_ids": [
                    str(item) for item in cap.applied_override_ids
                ],
                "actor_user_id": str(actor.user_id) if actor.user_id else None,
            },
        },
        summary={
            "enrollment_id": str(input_value.enrollment_id),
            "from_placement": from_placement,
            "to_placement": to_placement,
            "cascade": list(cascade),
            "restoration_candidates": list(restoration.candidates),
            "restored": list(restoration.restored),
        },
    )


def _validate_outgoing(
    input_value: ReplacePlacementInput, state: ReplacePlacementState
) -> OfferApplication | ExternalOfferRow | Rejection:
    """The named offer must be the placement the student actually holds."""
    if input_value.current_external_offer_id is not None:
        external = state.outgoing_external
        if external is None or external.enrollment_id != input_value.enrollment_id:
            return _rejection(
                INVALID_TRANSITION,
                "The external offer does not exist for this student",
                "current_external_offer_id",
            )
        if external.outcome is not Outcome.PLACEMENT:
            return _rejection(
                INVALID_TRANSITION,
                "Only a placement offer can be a student's placement",
                "current_external_offer_id",
            )
        if external.status is not ExternalStatus.ACCEPTED:
            return _rejection(
                STALE_VIEW,
                "That external offer is not the student's accepted placement",
                "current_external_offer_id",
            )
        return external

    target = _application_for_offer(state.applications, input_value.current_offer_id)
    if target is None or target.enrollment_id != input_value.enrollment_id:
        return _rejection(
            INVALID_TRANSITION, "The offer does not exist", "current_offer_id"
        )
    if target.outcome is not Outcome.PLACEMENT:
        return _rejection(
            INVALID_TRANSITION,
            "Only a placement offer can be a student's placement",
            "current_offer_id",
        )
    if target.current_offer_terminated:
        return _rejection(
            OFFER_TERMINATED, "The offer is already terminated", "current_offer_id"
        )
    if target.status is not ApplicationStatus.ACCEPTED:
        return _rejection(
            STALE_VIEW,
            "That offer is not the student's accepted placement",
            "current_offer_id",
        )
    return target


def _validate_incoming(
    input_value: ReplacePlacementInput, state: ReplacePlacementState
) -> OfferApplication | ExternalOfferRow | Rejection:
    """The incoming offer must be live, and its cycle must still be writable."""
    # The outgoing side is deliberately exempt from the archived-cycle rule:
    # last season's cycle is read-only, and refusing to correct a placement
    # recorded in it is how a wrong placement becomes permanent. The incoming
    # side is not exempt -- nothing new is written into an archived cycle.
    if state.incoming_cycle_archived:
        return _rejection(
            CYCLE_ARCHIVED,
            "The cycle the new offer belongs to is archived and is now read-only",
            "new_offer_id",
        )
    if input_value.new_external_offer_id is not None:
        external = state.incoming_external
        if external is None or external.enrollment_id != input_value.enrollment_id:
            return _rejection(
                INVALID_TRANSITION,
                "The external offer does not exist for this student",
                "new_external_offer_id",
            )
        if external.outcome is not Outcome.PLACEMENT:
            return _rejection(
                INVALID_TRANSITION,
                "Only a placement offer can become a student's placement",
                "new_external_offer_id",
            )
        if external.status is not ExternalStatus.OFFERED:
            return _rejection(
                STALE_VIEW,
                "That external offer is not waiting on a response",
                "new_external_offer_id",
            )
        return external

    target = _application_for_offer(state.applications, input_value.new_offer_id)
    if target is None or target.enrollment_id != input_value.enrollment_id:
        return _rejection(INVALID_TRANSITION, "The offer does not exist", "new_offer_id")
    if target.outcome is not Outcome.PLACEMENT:
        return _rejection(
            INVALID_TRANSITION,
            "Only a placement offer can become a student's placement",
            "new_offer_id",
        )
    if target.current_offer_terminated or target.current_offer_response is not None:
        return _rejection(
            STALE_VIEW, "That offer has already been responded to", "new_offer_id"
        )
    if target.status is not ApplicationStatus.OFFERED:
        return _rejection(
            STALE_VIEW, "That offer is not waiting on a response", "new_offer_id"
        )
    return target


def _supersession_payload(
    input_value: ReplacePlacementInput, *, key: str
) -> dict[str, object]:
    """Each half of the pair points at the other, so the audit reads as one act."""
    if key == "supersedes":
        return (
            {"supersedes_offer_id": str(input_value.current_offer_id)}
            if input_value.current_offer_id is not None
            else {
                "supersedes_external_offer_id": str(
                    input_value.current_external_offer_id
                )
            }
        )
    return (
        {"superseded_by_offer_id": str(input_value.new_offer_id)}
        if input_value.new_offer_id is not None
        else {"superseded_by_external_offer_id": str(input_value.new_external_offer_id)}
    )


def _with_payload(
    events: tuple[Event, ...], extra: dict[str, object]
) -> list[Event]:
    return [
        Event(
            application_id=event.application_id,
            event_type=event.event_type,
            from_status=event.from_status,
            to_status=event.to_status,
            from_round=event.from_round,
            to_round=event.to_round,
            reason=event.reason,
            payload={**event.payload, **extra},
        )
        for event in events
    ]


def _placement_payload(
    placement: OfferApplication | ExternalOfferRow,
) -> dict[str, object]:
    if isinstance(placement, OfferApplication):
        return {
            "kind": "portal",
            "offer_id": str(placement.current_offer_id),
            "application_id": str(placement.application_id),
            "job": placement.job_title,
            "company": placement.company_name,
            "cycle_id": str(placement.cycle_id),
            "cycle": placement.cycle_name,
        }
    return {
        "kind": "external",
        "external_offer_id": str(placement.id),
        "source": placement.source.value,
        "job": f"External {placement.outcome.value} offer",
        "company": placement.company_name,
        "cycle_id": (
            str(placement.attached_cycle_id) if placement.attached_cycle_id else None
        ),
        "cycle": placement.attached_cycle_name,
    }


def register_supersession_commands(registry: Registry) -> None:
    registry.command(
        name="replace_placement",
        input_model=ReplacePlacementInput,
        output_model=ReplacePlacementSummary,
        # Admin, and cycle-less on purpose. The outgoing offer can live in a
        # cycle this actor does not coordinate, or in an archived one, and a
        # coordinator must not be able to end a placement made elsewhere.
        actor="admin",
        scope="none",
        loader=_load_replace,
        # The outcome gate is not consulted: the command replaces the
        # placement rather than holding two, so there is nothing to override.
        # The cap is, because the incoming cycle's limit is still its own.
        rule_domains=(RuleDomain.OFFER_CAP,),
        spec_ids=("OFR-3", "OFR-5", "DER-1", "APP-4", "ELG-3"),
    )(_decide_replace_placement)
