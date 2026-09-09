"""Pure RND-3 round-finalization semantics."""

from uuid import UUID

from app.domain.shared import ApplicationStatus, Attendance, RoundResult
from app.domain.transitions import (
    RoundFinalizationState,
    decide_round_finalization,
)


def _row(number: int, attendance: Attendance) -> RoundFinalizationState:
    return RoundFinalizationState(
        application_id=UUID(int=number),
        status=ApplicationStatus.IN_PROGRESS,
        round_result=RoundResult.PENDING,
        attendance=attendance,
    )


def test_RND3_finalize_matrix_handles_pending_absent_excused_and_present() -> None:
    actions = decide_round_finalization(
        (
            _row(4, Attendance.PRESENT),
            _row(1, Attendance.PENDING),
            _row(3, Attendance.EXCUSED),
            _row(2, Attendance.ABSENT),
        ),
        strike_on_absence=True,
    )
    assert [action.application_id.int for action in actions] == [1, 2, 3]
    assert [action.attendance_after for action in actions] == [
        Attendance.ABSENT,
        Attendance.ABSENT,
        Attendance.EXCUSED,
    ]
    assert all(action.result_after is RoundResult.ELIMINATED for action in actions)
    assert all(action.status_after is ApplicationStatus.REJECTED for action in actions)
    assert [action.award_strike for action in actions] == [True, True, False]


def test_RND3_strike_policy_off_and_stale_rows_are_untouched() -> None:
    stale = RoundFinalizationState(
        application_id=UUID(int=2),
        status=ApplicationStatus.REJECTED,
        round_result=RoundResult.PENDING,
        attendance=Attendance.ABSENT,
    )
    decided = RoundFinalizationState(
        application_id=UUID(int=3),
        status=ApplicationStatus.IN_PROGRESS,
        round_result=RoundResult.ADVANCED,
        attendance=Attendance.ABSENT,
    )
    actions = decide_round_finalization(
        (_row(1, Attendance.ABSENT), stale, decided),
        strike_on_absence=False,
    )
    assert len(actions) == 1
    assert actions[0].award_strike is False
