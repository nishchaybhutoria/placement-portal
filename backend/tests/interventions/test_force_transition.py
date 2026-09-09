"""The previewed catch-all transition (Behavior INT-1, APP-4.17)."""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from app.core.errors import (
    APPLICATION_NOT_FOUND,
    CYCLE_ARCHIVED,
    INVALID_TRANSITION,
    STALE_VIEW,
    AuthorizationDenied,
    DomainRejection,
)
from app.core.plan import Preview, Result
from app.domain.shared import ApplicationStatus
from app.modules.interventions.commands import (
    UNPERFORMED_CONSEQUENCES,
    ForceTransitionInput,
)
from tests.interventions.conftest import (
    application_row,
    build_pipeline_world,
    build_test_executor,
    latest_event,
    queued_notifications,
    round_states,
    write_engine,
)

pytestmark = pytest.mark.asyncio


async def test_INT1_a_forced_transition_moves_the_status_and_nothing_else(
    clean_interventions: None,
) -> None:
    """Section 16 rule 1: the state and its effects commit together -- and here
    the declared set of effects is empty, which is the whole point."""
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    executor, _engine = build_test_executor()
    before = await round_states(world.application_id)

    result = await executor.run(
        "force_transition",
        ForceTransitionInput(
            cycle_id=world.cycle_id,
            application_id=world.application_id,
            to_status=ApplicationStatus.PENDING_OFFER,
            reason="Recovering from a mis-run bulk elimination",
        ),
        world.coordinator.actor,
    )
    assert isinstance(result, Result)

    row = await application_row(world.application_id)
    assert row["status"] == "pending_offer"
    # The position is not an implicit consequence to be tidied up either.
    assert row["current_round_id"] == world.rounds[1]
    assert await round_states(world.application_id) == before
    assert await queued_notifications() == []

    event = await latest_event(world.application_id)
    assert event["event_type"] == "forced_transition"
    assert event["from_status"] == "rejected"
    assert event["to_status"] == "pending_offer"
    assert event["reason"] == "Recovering from a mis-run bulk elimination"
    assert event["payload"]["implicit_consequences"] == "none"  # type: ignore[index]


async def test_INT1_the_preview_says_which_consequences_it_is_not_performing(
    clean_interventions: None,
) -> None:
    """The sentence is the safety mechanism, so it is asserted like one.

    Staff have to know what to run afterwards; a preview that said only "status
    will change" would leave a half-applied intervention behind every time.
    """
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    executor, _engine = build_test_executor()

    preview = await executor.run(
        "force_transition",
        ForceTransitionInput(
            cycle_id=world.cycle_id,
            application_id=world.application_id,
            to_status=ApplicationStatus.ACCEPTED,
            reason="Recorded off the portal by mistake",
        ),
        world.coordinator.actor,
        dry_run=True,
    )
    assert isinstance(preview, Preview)
    consequences = str(preview.summary["consequences"])
    assert "nothing else" in consequences
    unperformed = str(preview.summary["unperformed"])
    assert "cascade does not run" in unperformed
    assert "accept_offer" in unperformed
    assert unperformed == UNPERFORMED_CONSEQUENCES[ApplicationStatus.ACCEPTED]

    # Nothing was written by the preview, including the offer it names.
    assert (await application_row(world.application_id))["status"] == "rejected"


async def test_INT1_every_destination_status_has_its_own_unperformed_sentence() -> None:
    """A status with no sentence would preview as though it had no consequences."""
    assert set(UNPERFORMED_CONSEQUENCES) == set(ApplicationStatus)
    for status, sentence in UNPERFORMED_CONSEQUENCES.items():
        assert sentence.strip(), f"{status.value} has an empty consequence sentence"


async def test_INT1_a_self_transition_is_refused(clean_interventions: None) -> None:
    """APP-4.17 is "anything *else*": a self-transition writes nothing but an
    event claiming a move that never happened."""
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    executor, _engine = build_test_executor()

    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "force_transition",
            ForceTransitionInput(
                cycle_id=world.cycle_id,
                application_id=world.application_id,
                to_status=ApplicationStatus.REJECTED,
                reason="No-op",
            ),
            world.coordinator.actor,
        )
    reasons = rejected.value.rejection.reasons
    assert [reason.code for reason in reasons] == [INVALID_TRANSITION]
    assert reasons[0].path == "to_status"


async def test_INT1_a_forced_transition_requires_a_reason() -> None:
    """INT-1: every intervention carries a mandatory reason."""
    with pytest.raises(ValidationError):
        ForceTransitionInput(
            cycle_id=uuid4(),
            application_id=uuid4(),
            to_status=ApplicationStatus.REJECTED,
            reason="   ",
        )


async def test_INT1_a_stale_view_is_refused(clean_interventions: None) -> None:
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    executor, _engine = build_test_executor()

    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "force_transition",
            ForceTransitionInput(
                cycle_id=world.cycle_id,
                application_id=world.application_id,
                to_status=ApplicationStatus.WITHDRAWN,
                reason="Two coordinators, two screens",
                expected_status=ApplicationStatus.IN_PROGRESS,
            ),
            world.coordinator.actor,
        )
    assert [r.code for r in rejected.value.rejection.reasons] == [STALE_VIEW]


async def test_INT1_force_transition_is_cycle_scoped_and_archival_stops_it(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    other = await build_pipeline_world(status="rejected")
    executor, _engine = build_test_executor()

    payload = ForceTransitionInput(
        cycle_id=world.cycle_id,
        application_id=world.application_id,
        to_status=ApplicationStatus.WITHDRAWN,
        reason="Not this coordinator's cycle",
    )
    with pytest.raises(AuthorizationDenied):
        await executor.run("force_transition", payload, other.coordinator.actor)

    engine = write_engine()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("UPDATE cycles SET archived_at = now() WHERE id = :id"),
                {"id": world.cycle_id},
            )
    finally:
        await engine.dispose()

    with pytest.raises(DomainRejection) as archived:
        await executor.run("force_transition", payload, world.coordinator.actor)
    assert [r.code for r in archived.value.rejection.reasons] == [CYCLE_ARCHIVED]


async def test_INT1_an_application_outside_the_named_cycle_is_not_found(
    clean_interventions: None,
) -> None:
    del clean_interventions
    world = await build_pipeline_world(status="rejected")
    other = await build_pipeline_world(status="rejected")
    executor, _engine = build_test_executor()

    admin_actor = world.admin.actor
    with pytest.raises(DomainRejection) as rejected:
        await executor.run(
            "force_transition",
            ForceTransitionInput(
                cycle_id=other.cycle_id,
                application_id=world.application_id,
                to_status=ApplicationStatus.WITHDRAWN,
                reason="Wrong cycle for this application",
            ),
            admin_actor,
        )
    assert [r.code for r in rejected.value.rejection.reasons] == [APPLICATION_NOT_FOUND]
