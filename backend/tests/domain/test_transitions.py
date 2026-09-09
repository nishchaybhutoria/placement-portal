"""Pure APP-4, OFR-3/5 transition and cascade contracts."""

from itertools import product
from uuid import UUID

from app.core.plan import Rejection
from app.domain.shared import ApplicationStatus as S
from app.domain.shared import CycleKind, EventType, OfferExpiry, Outcome
from app.domain.transitions import (
    TRANSITIONS,
    ApplicationOfferState,
    EventHistoryItem,
    TransitionActor,
    TransitionContext,
    compute_acceptance_cascade,
    compute_restore_candidates,
    decide_transition,
    legal_transition_names,
)

CYCLE_A = UUID("00000000-0000-0000-0000-000000000301")
CYCLE_B = UUID("00000000-0000-0000-0000-000000000302")
CYCLE_C = UUID("00000000-0000-0000-0000-000000000303")
TARGET_APP = UUID("00000000-0000-0000-0000-000000000310")
TARGET_OFFER = UUID("00000000-0000-0000-0000-000000000311")
ROUND_A = UUID("00000000-0000-0000-0000-000000000312")


def _expected_placement_matrix() -> set[tuple[S | None, S, TransitionActor, str]]:
    expected: set[tuple[S | None, S, TransitionActor, str]] = {
        (None, S.IN_PROGRESS, TransitionActor.STUDENT, "apply"),
        (S.IN_PROGRESS, S.IN_PROGRESS, TransitionActor.STAFF, "advance"),
        (S.IN_PROGRESS, S.PENDING_OFFER, TransitionActor.STAFF, "advance_final"),
        (S.IN_PROGRESS, S.REJECTED, TransitionActor.STAFF, "eliminate"),
        (S.IN_PROGRESS, S.REJECTED, TransitionActor.STAFF, "bulk_reject"),
        (S.PENDING_OFFER, S.REJECTED, TransitionActor.STAFF, "bulk_reject"),
        (S.IN_PROGRESS, S.REJECTED, TransitionActor.STAFF, "cancel_job"),
        (S.PENDING_OFFER, S.REJECTED, TransitionActor.STAFF, "cancel_job"),
        (S.OFFERED, S.REJECTED, TransitionActor.STAFF, "cancel_job"),
        (S.IN_PROGRESS, S.OFFERED, TransitionActor.STAFF, "extend_offer"),
        (S.PENDING_OFFER, S.OFFERED, TransitionActor.STAFF, "extend_offer"),
        (S.OFFERED, S.ACCEPTED, TransitionActor.STUDENT, "accept"),
        (S.OFFERED, S.DECLINED, TransitionActor.STUDENT, "decline"),
        (S.OFFERED, S.DECLINED, TransitionActor.SYSTEM, "decline"),
        (S.IN_PROGRESS, S.WITHDRAWN, TransitionActor.STUDENT, "withdraw"),
        (S.IN_PROGRESS, S.AUTO_WITHDRAWN, TransitionActor.SYSTEM, "auto_withdraw"),
        (S.PENDING_OFFER, S.AUTO_WITHDRAWN, TransitionActor.SYSTEM, "auto_withdraw"),
        (S.OFFERED, S.OFFER_TERMINATED, TransitionActor.STAFF, "terminate_offer"),
        (S.ACCEPTED, S.OFFER_TERMINATED, TransitionActor.STAFF, "terminate_offer"),
        (S.REJECTED, S.IN_PROGRESS, TransitionActor.STAFF, "reinstate"),
        (S.WITHDRAWN, S.IN_PROGRESS, TransitionActor.STAFF, "reinstate"),
        (S.AUTO_WITHDRAWN, S.IN_PROGRESS, TransitionActor.STAFF, "reinstate"),
        (S.DECLINED, S.OFFERED, TransitionActor.STAFF, "re_extend"),
        (S.OFFER_TERMINATED, S.OFFERED, TransitionActor.STAFF, "re_extend"),
    }
    expected.update(
        (status, S.OFFERED, TransitionActor.STAFF, "direct_offer")
        for status in S
        if status not in {S.ACCEPTED, S.OFFERED}
    )
    return expected


def test_APP4_transition_legality_matrix_is_exhaustive() -> None:
    context = TransitionContext(CycleKind.PLACEMENT)
    expected = _expected_placement_matrix()
    actual: set[tuple[S | None, S, TransitionActor, str]] = set()
    for from_status, to_status, actor in product(
        (None, *tuple(S)), tuple(S), tuple(TransitionActor)
    ):
        for name in legal_transition_names(from_status, to_status, actor, context):
            actual.add((from_status, to_status, actor, name))
    assert actual == expected
    assert {transition.name for transition in TRANSITIONS} == {
        "apply",
        "advance",
        "advance_final",
        "eliminate",
        "bulk_reject",
        "cancel_job",
        "extend_offer",
        "accept",
        "decline",
        "withdraw",
        "auto_withdraw",
        "terminate_offer",
        "reinstate",
        "direct_offer",
        "re_extend",
        "force",
    }


def test_APP4_named_decide_helpers_enforce_legality_and_required_reasons() -> None:
    context = TransitionContext(CycleKind.PLACEMENT)
    legal = decide_transition(
        "withdraw",
        from_status=S.IN_PROGRESS,
        to_status=S.WITHDRAWN,
        actor=TransitionActor.STUDENT,
        context=context,
    )
    missing_reason = decide_transition(
        "eliminate",
        from_status=S.IN_PROGRESS,
        to_status=S.REJECTED,
        actor=TransitionActor.STAFF,
        context=context,
    )
    illegal = decide_transition(
        "accept",
        from_status=S.OFFERED,
        to_status=S.ACCEPTED,
        actor=TransitionActor.STAFF,
        context=context,
    )
    assert not isinstance(legal, Rejection)
    assert isinstance(missing_reason, Rejection)
    assert isinstance(illegal, Rejection)


def test_APP4_actor_context_for_open_and_expiry_transitions() -> None:
    open_context = TransitionContext(CycleKind.OPEN)
    assert legal_transition_names(S.OFFERED, S.ACCEPTED, TransitionActor.STAFF, open_context) == (
        "accept",
    )
    assert (
        legal_transition_names(S.OFFERED, S.ACCEPTED, TransitionActor.STUDENT, open_context) == ()
    )
    auto_accept = TransitionContext(CycleKind.INTERNSHIP, OfferExpiry.AUTO_ACCEPT)
    assert legal_transition_names(S.OFFERED, S.ACCEPTED, TransitionActor.SYSTEM, auto_accept) == (
        "accept",
    )


def test_APP4_force_matrix_is_staff_only_and_excludes_self() -> None:
    context = TransitionContext(CycleKind.PLACEMENT)
    for from_status, to_status, actor in product(tuple(S), tuple(S), tuple(TransitionActor)):
        names = legal_transition_names(from_status, to_status, actor, context, include_force=True)
        assert ("force" in names) is (
            actor is TransitionActor.STAFF and from_status is not to_status
        )


def _state(
    number: int,
    status: S,
    outcome: Outcome,
    cycle_id: UUID,
    cycle_kind: CycleKind,
    *,
    round_id: UUID | None = None,
) -> ApplicationOfferState:
    return ApplicationOfferState(
        application_id=UUID(int=number),
        status=status,
        outcome=outcome,
        cycle_id=cycle_id,
        cycle_kind=cycle_kind,
        current_round_id=round_id,
        current_offer_id=UUID(int=number + 1000) if status is S.OFFERED else None,
    )


def test_OFR3_placement_cascade_spans_three_cycles_including_open() -> None:
    target = ApplicationOfferState(
        TARGET_APP, S.OFFERED, Outcome.PLACEMENT, CYCLE_A, CycleKind.PLACEMENT
    )
    others = (
        _state(3, S.IN_PROGRESS, Outcome.PLACEMENT, CYCLE_C, CycleKind.OPEN),
        _state(1, S.OFFERED, Outcome.PLACEMENT, CYCLE_A, CycleKind.PLACEMENT),
        _state(2, S.PENDING_OFFER, Outcome.PLACEMENT, CYCLE_B, CycleKind.INTERNSHIP),
        _state(4, S.IN_PROGRESS, Outcome.INTERNSHIP, CYCLE_A, CycleKind.PLACEMENT),
    )
    actions = compute_acceptance_cascade(target, others, acceptance_offer_id=TARGET_OFFER)
    assert [action.application_id.int for action in actions] == [1, 2, 3]
    assert [action.to_status for action in actions] == [
        S.DECLINED,
        S.AUTO_WITHDRAWN,
        S.AUTO_WITHDRAWN,
    ]
    assert actions[0].event_type is EventType.AUTO_DECLINED
    assert all(action.payload["acceptance_offer_id"] == str(TARGET_OFFER) for action in actions)


def test_OFR3_internship_cascade_is_dedicated_same_cycle_only() -> None:
    target = ApplicationOfferState(
        TARGET_APP, S.OFFERED, Outcome.INTERNSHIP, CYCLE_A, CycleKind.INTERNSHIP
    )
    actions = compute_acceptance_cascade(
        target,
        (
            _state(1, S.OFFERED, Outcome.INTERNSHIP, CYCLE_A, CycleKind.INTERNSHIP),
            _state(2, S.IN_PROGRESS, Outcome.INTERNSHIP, CYCLE_B, CycleKind.INTERNSHIP),
            _state(
                3,
                S.IN_PROGRESS,
                Outcome.INTERNSHIP,
                CYCLE_A,
                CycleKind.INTERNSHIP,
            ),
            _state(4, S.IN_PROGRESS, Outcome.PLACEMENT, CYCLE_A, CycleKind.INTERNSHIP),
        ),
        acceptance_offer_id=TARGET_OFFER,
    )
    assert [action.application_id.int for action in actions] == [1, 3]


def test_OFR3_open_internship_acceptance_has_zero_cascade() -> None:
    target = ApplicationOfferState(
        TARGET_APP, S.OFFERED, Outcome.INTERNSHIP, CYCLE_A, CycleKind.OPEN
    )
    assert (
        compute_acceptance_cascade(
            target,
            (_state(1, S.OFFERED, Outcome.INTERNSHIP, CYCLE_A, CycleKind.OPEN),),
            acceptance_offer_id=TARGET_OFFER,
        )
        == ()
    )


def test_OFR5_terminate_restore_reconstructs_status_round_and_fresh_offer() -> None:
    withdrawn_app = UUID(int=1)
    declined_app = UUID(int=2)
    unrelated_offer = UUID(int=999)
    history = (
        EventHistoryItem(
            1,
            withdrawn_app,
            EventType.AUTO_WITHDRAWN,
            S.PENDING_OFFER,
            S.AUTO_WITHDRAWN,
            ROUND_A,
            ROUND_A,
            {"acceptance_offer_id": str(TARGET_OFFER)},
        ),
        EventHistoryItem(
            2,
            declined_app,
            EventType.AUTO_DECLINED,
            S.OFFERED,
            S.DECLINED,
            None,
            None,
            {"acceptance_offer_id": str(TARGET_OFFER)},
        ),
        EventHistoryItem(
            3,
            UUID(int=3),
            EventType.AUTO_WITHDRAWN,
            S.IN_PROGRESS,
            S.AUTO_WITHDRAWN,
            None,
            None,
            {"acceptance_offer_id": str(unrelated_offer)},
        ),
    )
    candidates = compute_restore_candidates(
        acceptance_offer_id=TARGET_OFFER,
        history=history,
        current_statuses={
            withdrawn_app: S.AUTO_WITHDRAWN,
            declined_app: S.DECLINED,
        },
    )
    assert [
        (item.restore_status, item.restore_round_id, item.requires_fresh_offer)
        for item in candidates
    ] == [
        (S.PENDING_OFFER, ROUND_A, False),
        (S.OFFERED, None, True),
    ]
