"""Reinstating a closed application (Behavior INT-1, APP-4.14)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.core.errors import (
    DUPLICATE_APPLICATION,
    INVALID_TRANSITION,
    JOB_CANCELLED,
    MEMBERSHIP_NOT_ACTIVE,
    ROUND_NOT_FOUND,
    STALE_VIEW,
    DomainRejection,
)
from app.core.plan import Preview, Result
from app.domain.shared import ApplicationStatus
from app.modules.interventions.commands import ReinstateApplicationInput
from tests.interventions.conftest import (
    application_row,
    build_pipeline_world,
    build_test_executor,
    latest_event,
    queued_notifications,
    round_states,
    seed_application_row,
    write_engine,
)

pytestmark = pytest.mark.asyncio


async def test_INT1_reinstating_to_an_earlier_round_clears_only_what_came_after(
    clean_interventions: None,
) -> None:
    """APP-4.14: later round-states cleared, earlier kept, exactly as previewed."""
    del clean_interventions
    world = await build_pipeline_world()
    executor, _engine = build_test_executor()

    payload = ReinstateApplicationInput(
        cycle_id=world.cycle_id,
        application_id=world.application_id,
        target_round_id=world.rounds[0],
        reason="Eliminated on the wrong shortlist",
        expected_status=ApplicationStatus.REJECTED,
    )
    preview = await executor.run(
        "reinstate_application", payload, world.coordinator.actor, dry_run=True
    )
    assert isinstance(preview, Preview)
    cleared = preview.summary["cleared_round_states"]
    kept = preview.summary["kept_round_states"]
    assert [row["round_name"] for row in cleared] == ["Technical"]  # type: ignore[index,union-attr]
    assert kept == []
    assert preview.summary["target_round_name"] == "Screening"

    result = await executor.run("reinstate_application", payload, world.coordinator.actor)
    assert isinstance(result, Result)
    # Previews never lie: the executed summary is the previewed one.
    assert result.summary == preview.summary

    row = await application_row(world.application_id)
    assert row["status"] == "in_progress"
    assert row["current_round_id"] == world.rounds[0]

    states = await round_states(world.application_id)
    assert [state["ord"] for state in states] == [1]
    assert states[0]["result"] == "pending"
    # RND-3's remedy is "edit the attendance sheet then reinstate", so the mark
    # the sheet recorded survives the reinstatement that follows it.
    assert states[0]["attendance"] == "present"


async def test_INT1_reinstating_in_place_reopens_the_round_it_was_closed_in(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world()
    executor, _engine = build_test_executor()

    result = await executor.run(
        "reinstate_application",
        ReinstateApplicationInput(
            cycle_id=world.cycle_id,
            application_id=world.application_id,
            target_round_id=world.rounds[1],
            reason="Attendance sheet corrected",
        ),
        world.coordinator.actor,
    )
    assert isinstance(result, Result)
    assert result.summary["cleared_round_states"] == []
    assert [row["round_name"] for row in result.summary["kept_round_states"]] == [  # type: ignore[index,union-attr]
        "Screening"
    ]

    states = await round_states(world.application_id)
    assert [(state["ord"], state["result"]) for state in states] == [
        (1, "advanced"),
        (2, "pending"),
    ]
    assert states[1]["attendance"] == "absent"


async def test_INT1_an_auto_withdrawn_application_returns_to_its_exact_position(
    clean_interventions: None,
) -> None:
    """CYC-4 preserves the position underneath precisely so this can restore it."""
    del clean_interventions
    world = await build_pipeline_world(status="auto_withdrawn", results=("advanced", "pending"))
    executor, _engine = build_test_executor()

    before = await round_states(world.application_id)
    result = await executor.run(
        "reinstate_application",
        ReinstateApplicationInput(
            cycle_id=world.cycle_id,
            application_id=world.application_id,
            target_round_id=world.rounds[1],
            reason="The accepted offer was terminated",
        ),
        world.coordinator.actor,
    )
    assert isinstance(result, Result)

    row = await application_row(world.application_id)
    assert row["status"] == "in_progress"
    assert row["current_round_id"] == world.rounds[1]
    assert await round_states(world.application_id) == before


async def test_INT1_reinstate_is_blocked_with_duplicate_application(
    clean_interventions: None,
) -> None:
    """The student withdrew and applied again, so the pair already has a live row.

    Without this the partial-unique index would refuse the write and the
    coordinator would see a 500 where they should see a reason and a next step.
    """
    del clean_interventions
    world = await build_pipeline_world(status="withdrawn")
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await seed_application_row(
                connection,
                job_id=world.job_id,
                enrollment_id=world.student.enrollment_id,
                status="in_progress",
                current_round_id=world.rounds[0],
            )
    finally:
        await engine.dispose()

    executor, _engine = build_test_executor()
    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "reinstate_application",
            ReinstateApplicationInput(
                cycle_id=world.cycle_id,
                application_id=world.application_id,
                target_round_id=world.rounds[0],
                reason="Reverse the withdrawal",
            ),
            world.coordinator.actor,
        )
    assert DUPLICATE_APPLICATION in [
        reason.code for reason in rejected.value.rejection.reasons
    ]
    assert (await application_row(world.application_id))["status"] == "withdrawn"


async def test_INT1_reinstate_refuses_to_manufacture_a_checker_finding(
    clean_interventions: None,
) -> None:
    """A live application on a non-active membership is corruption by definition.

    The consistency checker reports exactly this state, so an intervention that
    created it would be manufacturing the finding it would then be asked to fix.
    """
    del clean_interventions
    world = await build_pipeline_world(membership_status="removed")
    executor, _engine = build_test_executor()

    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "reinstate_application",
            ReinstateApplicationInput(
                cycle_id=world.cycle_id,
                application_id=world.application_id,
                target_round_id=world.rounds[0],
                reason="Bring them back",
            ),
            world.coordinator.actor,
        )
    assert MEMBERSHIP_NOT_ACTIVE in [
        reason.code for reason in rejected.value.rejection.reasons
    ]


async def test_INT1_reinstate_refuses_a_cancelled_job_and_a_live_application(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world()
    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE jobs SET cancelled_at = now() WHERE id = :id"),
                {"id": world.job_id},
            )
    finally:
        await engine.dispose()

    executor, _engine = build_test_executor()
    with pytest.raises(DomainRejection) as cancelled:
        await executor.run(
            "reinstate_application",
            ReinstateApplicationInput(
                cycle_id=world.cycle_id,
                application_id=world.application_id,
                target_round_id=world.rounds[0],
                reason="Bring them back",
            ),
            world.coordinator.actor,
        )
    assert JOB_CANCELLED in [r.code for r in cancelled.value.rejection.reasons]

    live = await build_pipeline_world(status="in_progress")
    with pytest.raises(DomainRejection) as wrong_status:
        await executor.run(
            "reinstate_application",
            ReinstateApplicationInput(
                cycle_id=live.cycle_id,
                application_id=live.application_id,
                target_round_id=live.rounds[0],
                reason="Already live",
            ),
            live.coordinator.actor,
        )
    assert [r.code for r in wrong_status.value.rejection.reasons] == [INVALID_TRANSITION]


async def test_INT1_reinstate_checks_the_round_belongs_to_the_job_and_the_view_is_fresh(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world()
    executor, _engine = build_test_executor()

    with pytest.raises(DomainRejection) as stale:
        await executor.run(
            "reinstate_application",
            ReinstateApplicationInput(
                cycle_id=world.cycle_id,
                application_id=world.application_id,
                target_round_id=world.rounds[0],
                reason="Refresh first",
                expected_status=ApplicationStatus.WITHDRAWN,
            ),
            world.coordinator.actor,
        )
    assert [r.code for r in stale.value.rejection.reasons] == [STALE_VIEW]

    other = await build_pipeline_world()
    with pytest.raises(DomainRejection) as wrong_round:
        await executor.run(
            "reinstate_application",
            ReinstateApplicationInput(
                cycle_id=other.cycle_id,
                application_id=other.application_id,
                target_round_id=world.rounds[0],
                reason="Round from another job",
            ),
            other.coordinator.actor,
        )
    assert ROUND_NOT_FOUND in [r.code for r in wrong_round.value.rejection.reasons]


async def test_INT1_reinstatement_notifies_the_student_by_default(
    clean_interventions: None,
) -> None:
    """the design review section 4.28: the catalog's reinstatement omission is closed.

    A student who was rejected and is now sitting in a round again must be told,
    rather than discovering it by chance; the notify choice INT-1 promises is on
    the input, defaulted on.
    """
    del clean_interventions
    world = await build_pipeline_world()
    executor, _engine = build_test_executor()

    await executor.run(
        "reinstate_application",
        ReinstateApplicationInput(
            cycle_id=world.cycle_id,
            application_id=world.application_id,
            target_round_id=world.rounds[1],
            reason="Shortlist corrected",
        ),
        world.coordinator.actor,
    )
    queued = await queued_notifications()
    assert [item["event_key"] for item in queued] == ["reinstated"]
    context = queued[0]["context"]
    assert context["round"] == "Technical"  # type: ignore[index]
    assert context["reason"] == "Shortlist corrected"  # type: ignore[index]

    event = await latest_event(world.application_id)
    assert event["event_type"] == "reinstated"
    assert event["to_status"] == "in_progress"
    assert event["reason"] == "Shortlist corrected"
    assert event["payload"]["notified"] is True  # type: ignore[index]


async def test_INT1_reinstatement_can_be_run_silently(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world()
    executor, _engine = build_test_executor()

    await executor.run(
        "reinstate_application",
        ReinstateApplicationInput(
            cycle_id=world.cycle_id,
            application_id=world.application_id,
            target_round_id=world.rounds[1],
            reason="Bulk correction, students told in person",
            notify=False,
        ),
        world.coordinator.actor,
    )
    assert await queued_notifications() == []
    event = await latest_event(world.application_id)
    assert event["payload"]["notified"] is False  # type: ignore[index]
