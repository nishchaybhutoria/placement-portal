"""Strikes, penalties, conversion and revocation (Behavior DIS)."""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.errors import (
    ENROLLMENT_NOT_FOUND,
    PENALTY_ALREADY_REVOKED,
    PENALTY_NOT_FOUND,
    STRIKE_ALREADY_REVOKED,
    STRIKE_NOT_FOUND,
    DomainRejection,
)
from app.core.plan import Result
from tests.discipline.conftest import (
    DisciplineWorld,
    build_test_executor,
    rows,
    seed_discipline_world,
    set_threshold,
    strike_ids,
)

pytestmark = pytest.mark.asyncio


async def _run(world: DisciplineWorld, command: str, payload: dict[str, object]) -> Result:
    executor, engine = build_test_executor()
    model = executor.registry.commands[command].input_model
    try:
        return cast(
            Result,
            await executor.run(command, model.model_validate(payload), world.admin.actor),
        )
    finally:
        await engine.dispose()


async def _award(world: DisciplineWorld, reason: str = "Missed a round") -> Result:
    return await _run(
        world,
        "award_strike",
        {"enrollment_id": str(world.student.enrollment_id), "reason": reason},
    )


async def _penalties(enrollment_id: UUID) -> list[sa.RowMapping]:
    return await rows(
        "SELECT id, reasons, from_strikes, is_active, revoked_at, revoked_by "
        "FROM penalties WHERE enrollment_id = :id ORDER BY created_at, id",
        {"id": enrollment_id},
    )


async def _strikes(enrollment_id: UUID) -> list[sa.RowMapping]:
    return await rows(
        "SELECT id, reason, source, is_active, consumed_by_penalty_id "
        "FROM strikes WHERE enrollment_id = :id ORDER BY created_at, id",
        {"id": enrollment_id},
    )


def _notifications() -> str:
    return (
        "SELECT task_name, args FROM procrastinate_jobs ORDER BY id"
    )


async def _sent() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in await rows(_notifications()):
        args = row["args"]
        out.append(cast("dict[str, Any]", json.loads(args) if isinstance(args, str) else args))
    return out


async def test_DIS_a_manual_strike_lands_active_and_unconsumed() -> None:
    world = await seed_discipline_world()
    await set_threshold(2)

    result = await _award(world)

    standing = await _strikes(world.student.enrollment_id)
    assert [(row["source"], row["is_active"]) for row in standing] == [("manual", True)]
    assert standing[0]["consumed_by_penalty_id"] is None
    assert result.summary["strike_total"] == 1
    assert result.summary["penalties_created"] == 0


async def test_DIS_the_student_is_told_the_running_total() -> None:
    world = await seed_discipline_world()
    await set_threshold(2)

    await _award(world, "First")

    added = [item for item in await _sent() if item["event_key"] == "strike_added"]
    assert [item["context"]["total"] for item in added] == [1]
    assert added[0]["context"]["reason"] == "First"
    assert added[0]["recipient"] == world.student.email


async def test_DIS_reaching_the_global_threshold_converts_atomically() -> None:
    world = await seed_discipline_world()
    await set_threshold(2)

    await _award(world, "First")
    result = await _award(world, "Second")

    penalties = await _penalties(world.student.enrollment_id)
    assert len(penalties) == 1
    assert penalties[0]["from_strikes"] is True
    # Reasons are concatenated, oldest first, so the penalty says what it is for.
    assert penalties[0]["reasons"] == "First; Second"
    standing = await _strikes(world.student.enrollment_id)
    consumed = [row["consumed_by_penalty_id"] for row in standing]
    assert consumed == [penalties[0]["id"], penalties[0]["id"]]
    assert result.summary["penalties_created"] == 1


async def test_DIS_the_conversion_notifies_the_student() -> None:
    world = await seed_discipline_world()
    await set_threshold(2)

    await _award(world, "First")
    await _award(world, "Second")

    keys = [item["event_key"] for item in await _sent()]
    assert keys.count("penalty_added") == 1


async def test_DIS_a_blank_threshold_disables_conversion_entirely() -> None:
    world = await seed_discipline_world()
    await set_threshold(None)

    for index in range(4):
        await _award(world, f"Strike {index}")

    assert await _penalties(world.student.enrollment_id) == []
    assert all(
        row["consumed_by_penalty_id"] is None
        for row in await _strikes(world.student.enrollment_id)
    )


async def test_DIS_the_threshold_is_read_when_the_command_runs_not_when_awarded() -> None:
    """Three strikes under a disabled threshold convert once it is set to 3."""
    world = await seed_discipline_world()
    await set_threshold(None)
    await _award(world, "First")
    await _award(world, "Second")
    assert await _penalties(world.student.enrollment_id) == []

    await set_threshold(3)
    await _award(world, "Third")

    penalties = await _penalties(world.student.enrollment_id)
    assert len(penalties) == 1
    assert penalties[0]["reasons"] == "First; Second; Third"


async def test_DIS_revoking_a_strike_dissolves_the_penalty_it_supported() -> None:
    world = await seed_discipline_world()
    await set_threshold(2)
    await _award(world, "First")
    await _award(world, "Second")
    penalty_id = (await _penalties(world.student.enrollment_id))[0]["id"]
    first_strike = (await strike_ids(world.student.enrollment_id))[0]

    result = await _run(
        world, "revoke_strike", {"strike_id": str(first_strike), "reason": "Wrong sheet"}
    )

    penalties = await _penalties(world.student.enrollment_id)
    assert penalties[0]["id"] == penalty_id
    assert penalties[0]["is_active"] is False
    assert penalties[0]["revoked_at"] is not None
    # The surviving strike un-consumes, so it can support a future conversion.
    standing = await _strikes(world.student.enrollment_id)
    assert [(row["is_active"], row["consumed_by_penalty_id"]) for row in standing] == [
        (False, None),
        (True, None),
    ]
    assert result.summary["penalties_dissolved"] == 1
    assert result.summary["strike_total"] == 1


async def test_DIS_an_unconsumed_strike_revokes_without_touching_a_penalty() -> None:
    world = await seed_discipline_world()
    await set_threshold(None)
    await _award(world, "Only")
    only = (await strike_ids(world.student.enrollment_id))[0]

    result = await _run(
        world, "revoke_strike", {"strike_id": str(only), "reason": "Mistake"}
    )

    assert result.summary["penalties_dissolved"] == 0
    assert result.summary["strike_total"] == 0
    assert (await _strikes(world.student.enrollment_id))[0]["is_active"] is False


async def test_DIS_the_revoked_student_is_told_the_new_total() -> None:
    world = await seed_discipline_world()
    await set_threshold(None)
    await _award(world, "Only")
    only = (await strike_ids(world.student.enrollment_id))[0]

    await _run(world, "revoke_strike", {"strike_id": str(only), "reason": "Mistake"})

    revoked = [item for item in await _sent() if item["event_key"] == "strike_revoked"]
    assert [item["context"]["total"] for item in revoked] == [0]


async def test_DIS_who_revoked_a_strike_is_recorded_in_the_audit_log() -> None:
    """The strikes table has no revoked_by, so the audit row is the only record."""
    world = await seed_discipline_world()
    await set_threshold(None)
    await _award(world, "Only")
    only = (await strike_ids(world.student.enrollment_id))[0]

    await _run(world, "revoke_strike", {"strike_id": str(only), "reason": "Wrong sheet"})

    entry = (
        await rows(
            "SELECT actor_user_id, subject_type, subject_id, details FROM audit_log "
            "WHERE subject_type = 'strike'"
        )
    )[0]
    assert entry["subject_id"] == only
    assert entry["actor_user_id"] == world.admin.user_id
    assert entry["details"]["reason"] == "Wrong sheet"


async def test_DIS_revoking_a_strike_twice_is_refused() -> None:
    world = await seed_discipline_world()
    await set_threshold(None)
    await _award(world, "Only")
    only = (await strike_ids(world.student.enrollment_id))[0]
    await _run(world, "revoke_strike", {"strike_id": str(only), "reason": "Mistake"})

    with pytest.raises(DomainRejection) as rejection:
        await _run(world, "revoke_strike", {"strike_id": str(only), "reason": "Again"})

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        STRIKE_ALREADY_REVOKED
    ]


async def test_DIS_a_direct_penalty_consumes_nothing_and_blocks_immediately() -> None:
    world = await seed_discipline_world()
    await set_threshold(2)
    await _award(world, "Standing")

    await _run(
        world,
        "award_penalty",
        {"enrollment_id": str(world.student.enrollment_id), "reasons": "Plagiarism"},
    )

    penalties = await _penalties(world.student.enrollment_id)
    assert [(row["from_strikes"], row["is_active"]) for row in penalties] == [(False, True)]
    # The standing strike is untouched: a direct award is not a conversion.
    standing = await _strikes(world.student.enrollment_id)
    assert standing[0]["consumed_by_penalty_id"] is None


async def test_DIS_revoking_a_penalty_leaves_its_strikes_consumed() -> None:
    world = await seed_discipline_world()
    await set_threshold(2)
    await _award(world, "First")
    await _award(world, "Second")
    penalty_id = (await _penalties(world.student.enrollment_id))[0]["id"]

    await _run(
        world, "revoke_penalty", {"penalty_id": str(penalty_id), "reason": "Appealed"}
    )

    penalties = await _penalties(world.student.enrollment_id)
    assert penalties[0]["is_active"] is False
    assert penalties[0]["revoked_by"] == world.admin.user_id
    # DIS is explicit: the strikes stay consumed unless they are revoked too.
    assert all(
        row["consumed_by_penalty_id"] == penalty_id
        for row in await _strikes(world.student.enrollment_id)
    )


async def test_DIS_revoking_a_penalty_twice_is_refused() -> None:
    world = await seed_discipline_world()
    await set_threshold(None)
    await _run(
        world,
        "award_penalty",
        {"enrollment_id": str(world.student.enrollment_id), "reasons": "Once"},
    )
    penalty_id = (await _penalties(world.student.enrollment_id))[0]["id"]
    await _run(world, "revoke_penalty", {"penalty_id": str(penalty_id), "reason": "A"})

    with pytest.raises(DomainRejection) as rejection:
        await _run(world, "revoke_penalty", {"penalty_id": str(penalty_id), "reason": "B"})

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        PENALTY_ALREADY_REVOKED
    ]


@pytest.mark.parametrize(
    ("command", "payload_key", "code"),
    [
        ("revoke_strike", "strike_id", STRIKE_NOT_FOUND),
        ("revoke_penalty", "penalty_id", PENALTY_NOT_FOUND),
    ],
)
async def test_DIS_revoking_something_that_does_not_exist_is_refused(
    command: str, payload_key: str, code: str
) -> None:
    world = await seed_discipline_world()

    with pytest.raises(DomainRejection) as rejection:
        await _run(world, command, {payload_key: str(uuid4()), "reason": "Missing"})

    assert [reason.code for reason in rejection.value.rejection.reasons] == [code]


async def test_DIS_awarding_against_an_unknown_enrollment_is_refused() -> None:
    world = await seed_discipline_world()

    with pytest.raises(DomainRejection) as rejection:
        await _run(
            world, "award_strike", {"enrollment_id": str(uuid4()), "reason": "Nobody"}
        )

    assert [reason.code for reason in rejection.value.rejection.reasons] == [
        ENROLLMENT_NOT_FOUND
    ]


async def test_DIS_a_strike_needs_a_reason() -> None:
    executor, engine = build_test_executor()
    model = executor.registry.commands["award_strike"].input_model
    try:
        with pytest.raises(ValueError):
            model.model_validate({"enrollment_id": str(uuid4()), "reason": "   "})
    finally:
        await engine.dispose()
