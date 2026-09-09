"""ANA-1 definitions, asserted as sets of students rather than as totals.

Two layers, because neither is sufficient alone.

**Layer A** writes the expectation down by hand: for each of the eleven
enrollments in the world, whether ANA-1 counts it and the sentence that says
why.  A count assertion cannot do this -- two mistakes cancel in a total, and a
`placed = 4` that is right for the wrong four students passes forever.

**Layer B** pins the same figures against `modules/offers/derivations.py`, the
module the ELG-3 gates consult, and then one level further: the students the
dashboard calls placed must be exactly the students `apply` refuses with the
outcome gate (the design review 4.22).  A dashboard that says placed while the gate
lets them apply is the same failure as a job card promising an eligibility the
command denies, and it is the one this milestone is most able to introduce.
"""

from __future__ import annotations

import os
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import OUTCOME_GATE_PLACEMENT, DomainRejection
from app.modules.analytics import metrics
from app.modules.analytics.metrics import MetricFilters
from app.modules.offers.derivations import offer_facts, placement_placed_global
from tests.analytics.conftest import (
    NOT_PLACED_IN_CYCLE,
    PLACED_IN_CYCLE,
    DefinitionWorld,
    build_definition_world,
    build_gate_probe,
    build_test_executor,
    record_external_offer,
)

pytestmark = pytest.mark.asyncio


async def _world() -> DefinitionWorld:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            return await build_definition_world(connection)
    finally:
        await engine.dispose()


def _cycle(world: DefinitionWorld, **changes: object) -> MetricFilters:
    return MetricFilters(cycle_ids=(world.cycle_id,)).narrow(**changes)


# ---------------------------------------------------------------------------
# Layer A -- the expectation, written down.
# ---------------------------------------------------------------------------


async def test_ANA1_placed_counts_exactly_the_students_the_definition_names(
    clean_cycles: None,
) -> None:
    """Every clause of ANA-1's placed sentence, asserted one enrollment at a time."""
    world = await _world()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            cohort = await metrics.placed(connection, _cycle(world))
    finally:
        await engine.dispose()

    for key, why in PLACED_IN_CYCLE.items():
        assert world.enrollment(key) in cohort.ids, (
            f"{key} must be placed in this cycle: {why}"
        )
    for key, why in NOT_PLACED_IN_CYCLE.items():
        assert world.enrollment(key) not in cohort.ids, (
            f"{key} must NOT be placed in this cycle: {why}"
        )
    # Set equality on top of the per-row messages: the loops above catch a
    # wrong verdict on a known student, this catches a student the query
    # invented or lost entirely.
    assert world.explain(cohort.ids) == set(PLACED_IN_CYCLE)


async def test_ANA1_the_placed_split_partitions_the_placed_figure(
    clean_cycles: None,
) -> None:
    """on-portal vs PPO vs off-campus vs other, summing to placed."""
    world = await _world()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            cohort = await metrics.placed(connection, _cycle(world))
    finally:
        await engine.dispose()

    assert cohort.split == {"portal": 2, "ppo": 1, "off_campus": 1, "other": 0}
    assert sum(cohort.split.values()) == cohort.count
    assert world.explain(cohort.by_source["portal"]) == {
        "accepted_portal",
        "forced_status",
    }
    assert world.explain(cohort.by_source["ppo"]) == {"ppo_external"}
    assert world.explain(cohort.by_source["off_campus"]) == {"off_campus_external"}


async def test_ANA1_registered_applied_and_offered_count_their_own_definitions(
    clean_cycles: None,
) -> None:
    world = await _world()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            computed = await metrics.funnel(connection, _cycle(world))
    finally:
        await engine.dispose()

    # Registered is active memberships -- the pending member is the one out.
    assert world.explain(computed.registered.ids) == set(PLACED_IN_CYCLE) | (
        set(NOT_PLACED_IN_CYCLE) - {"pending_member"}
    )
    # Applied is "ever created", so the terminated student still counts, and
    # the pending member counts despite never being registered: ANA-1 defines
    # the two over different populations and this is what that looks like.
    assert world.explain(computed.applied.ids) == {
        "accepted_portal",
        "forced_status",
        "terminated_portal",
        "applied_only",
        "pending_member",
    }
    # Offered counts a since-terminated portal offer and an attached external
    # still sitting at 'offered' (the design review 4.30h): it is a reach statistic.
    assert world.explain(computed.offered.ids) == {
        "accepted_portal",
        "forced_status",
        "terminated_portal",
        "ppo_external",
        "off_campus_external",
        "offered_external",
    }


async def test_ANA1_placement_rate_is_placed_over_registered(
    clean_cycles: None,
) -> None:
    world = await _world()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            computed = await metrics.funnel(connection, _cycle(world))
    finally:
        await engine.dispose()

    body = computed.as_dict()
    assert body["placement_rate"] == {
        "numerator": 4,
        "denominator": 10,
        "ratio": "0.4000",
    }
    # The rate ships its arithmetic so nothing downstream recomputes it and
    # gets a third answer.
    assert computed.placed.count == 4
    assert computed.registered.count == 10
    # Both levels of the published split sum to the figure above them.
    assert body["placed"] == {
        "total": 4,
        "split": {"portal": 2, "external": 2},
        "external_sources": {"ppo": 1, "off_campus": 1, "other": 0},
        "discarded_acceptances": 0,
    }


async def test_ANA3_the_seeking_denominator_excludes_tagged_memberships(
    clean_cycles: None,
) -> None:
    """Outcome tags shrink the honest denominator, and only that one."""
    world = await _world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE cycle_memberships SET outcome_tag = 'higher_studies' "
                    "WHERE cycle_id = :cycle AND enrollment_id = :enrollment"
                ),
                {
                    "cycle": world.cycle_id,
                    "enrollment": world.enrollment("registered_only"),
                },
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            computed = await metrics.funnel(connection, _cycle(world))
    finally:
        await engine.dispose()

    body = computed.as_dict()
    assert body["registered"] == 10
    assert body["registered_seeking"] == 9
    # Both rates are reported and both are labelled; the unqualified one stays
    # ANA-1's (the design review 4.30b).
    assert body["placement_rate"] == {
        "numerator": 4,
        "denominator": 10,
        "ratio": "0.4000",
    }
    assert body["placement_rate_seeking"] == {
        "numerator": 4,
        "denominator": 9,
        "ratio": "0.4444",
    }


async def test_ANA1_compensation_prefers_the_program_row_and_states_coverage(
    clean_cycles: None,
) -> None:
    """Per-program CTC over job CTC, external offers on their own figure."""
    world = await _world()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            block = await metrics.compensation(
                connection, _cycle(world), outcome="placement"
            )
            internship = await metrics.compensation(
                connection, _cycle(world), outcome="internship"
            )
    finally:
        await engine.dispose()

    # accepted_portal resolves to its per-program row (21.50), not the job's
    # 18.00; forced_status has an empty snapshot and falls back to 12.00; the
    # two externals carry their own recorded figures.
    assert block.unit == "lpa"
    assert block.placed == 4
    assert block.covered == 4
    assert block.minimum == Decimal("12.00")
    assert block.maximum == Decimal("30.00")
    assert block.median == Decimal("22.75")
    assert block.mean == Decimal("21.88")
    # Nothing pooled across units: an internship block over a placement cycle
    # is empty, not a number borrowed from the other outcome.
    assert internship.unit == "inr_per_month"
    assert internship.placed == 0
    assert internship.covered == 0
    assert internship.median is None


async def test_ANA1_a_placed_student_without_a_recorded_ctc_shows_in_coverage(
    clean_cycles: None,
) -> None:
    """The gap between placed and covered is the statistic's own caveat."""
    world = await _world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await record_external_offer(
                connection,
                enrollment_id=world.enrollment("registered_only"),
                created_by=world.admin_id,
                source="off_campus",
                attached_cycle_id=world.cycle_id,
                ctc_lpa=None,
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            block = await metrics.compensation(
                connection, _cycle(world), outcome="placement"
            )
            cohort = await metrics.placed(connection, _cycle(world))
    finally:
        await engine.dispose()

    assert cohort.count == 5
    assert block.placed == 5
    assert block.covered == 4
    # The uncompensated row moves neither the median nor the mean.
    assert block.median == Decimal("22.75")
    assert block.mean == Decimal("21.88")


async def test_ANA1_multiple_acceptances_count_once_under_the_most_recent(
    clean_cycles: None,
) -> None:
    """the design review 4.30e: most recent, not largest, and the split stays a partition."""
    world = await _world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            # A later, smaller external acceptance for a student already placed
            # on the portal.  Taking the largest would keep the portal figure;
            # taking the most recent moves them to off-campus and lowers the
            # published mean, which is the direction the ruling insists on.
            await record_external_offer(
                connection,
                enrollment_id=world.enrollment("accepted_portal"),
                created_by=world.admin_id,
                source="off_campus",
                attached_cycle_id=world.cycle_id,
                ctc_lpa="9.00",
                responded_on=date(2030, 6, 1),
            )
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            cohort = await metrics.placed(connection, _cycle(world))
            block = await metrics.compensation(
                connection, _cycle(world), outcome="placement"
            )
    finally:
        await engine.dispose()

    assert cohort.count == 4, "the student is placed once, not twice"
    assert sum(cohort.split.values()) == cohort.count
    assert world.explain(cohort.by_source["off_campus"]) == {
        "accepted_portal",
        "off_campus_external",
    }
    assert world.explain(cohort.by_source["portal"]) == {"forced_status"}
    assert cohort.discarded_acceptances == 1
    assert block.covered == 4
    assert block.minimum == Decimal("9.00")


# ---------------------------------------------------------------------------
# Layer B -- equivalence with the derivations, and with the gate itself.
# ---------------------------------------------------------------------------


async def test_DER1_analytics_and_the_derivations_agree_enrollment_by_enrollment(
    clean_cycles: None,
) -> None:
    """The portal-wide placed set is exactly DER-1's, student by student."""
    world = await _world()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            portal_wide = await metrics.placed(
                connection, MetricFilters(outcome="placement")
            )
            derived = {
                key: await placement_placed_global(connection, student.enrollment_id)
                for key, student in world.students.items()
            }
    finally:
        await engine.dispose()

    for key, student in world.students.items():
        assert (student.enrollment_id in portal_wide.ids) == derived[key], (
            f"analytics and derivations.placement_placed_global disagree on {key}"
        )
    # Portal-wide is the only scope where an unattached external acceptance
    # counts, and the only one where another cycle's acceptance does.
    assert world.explain(portal_wide.ids) == {
        "accepted_portal",
        "forced_status",
        "ppo_external",
        "off_campus_external",
        "unattached_external",
        "other_cycle",
    }


async def test_DER1_cycle_scoped_placed_matches_the_cycle_local_offer_facts(
    clean_cycles: None,
) -> None:
    """The cycle figure agrees with what the gates load for that cycle."""
    world = await _world()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            cohort = await metrics.placed(connection, _cycle(world))
            facts = {
                key: await offer_facts(
                    connection, student.enrollment_id, world.cycle_id
                )
                for key, student in world.students.items()
            }
    finally:
        await engine.dispose()

    for key, student in world.students.items():
        # cap_used counts accepted rows in this cycle from both sources, which
        # is the same population the cycle's placed figure counts over.
        assert (student.enrollment_id in cohort.ids) == (facts[key].cap_used > 0), (
            f"analytics and derivations.offer_facts disagree on {key} "
            f"({world.students[key].why})"
        )


async def test_ANA1_what_the_dashboard_calls_placed_is_what_apply_refuses(
    clean_cycles: None,
) -> None:
    """the design review 4.22, one level up: the figure and the gate are one answer.

    Placement is once per student anywhere, so a single published placement job
    in a third cycle is enough to ask the gate about all eleven of them.
    """
    world = await _world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            probe_cycle, probe_job = await build_gate_probe(connection, world)
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            reported = await metrics.placed(
                connection, MetricFilters(outcome="placement")
            )
    finally:
        await engine.dispose()

    refused: set[UUID] = set()
    executor, engine = build_test_executor()
    model = executor.registry.commands["apply"].input_model
    try:
        for student in world.students.values():
            payload = model.model_validate(
                {
                    "cycle_id": str(probe_cycle),
                    "job_id": str(probe_job),
                    "enrollment_id": str(student.enrollment_id),
                }
            )
            try:
                await executor.run(
                    "apply", payload, student.actor, dry_run=True
                )
            except DomainRejection as rejection:
                codes = {
                    asdict(reason)["code"] for reason in rejection.rejection.reasons
                }
                if OUTCOME_GATE_PLACEMENT in codes:
                    refused.add(student.enrollment_id)
    finally:
        await engine.dispose()

    assert world.explain(frozenset(refused)) == world.explain(reported.ids), (
        "the students the dashboard reports as placed must be exactly the "
        "students the placement gate refuses"
    )
    # Equality between two empty sets, or between two full ones, would prove
    # nothing.  The pin only means something while the gate is actually
    # dividing this population, so that is asserted rather than assumed.
    assert 0 < len(refused) < len(world.students), (
        "the probe job must divide the world: every student blocked, or none, "
        "makes the equality above vacuous"
    )
    assert world.explain(frozenset(refused)) == {
        "accepted_portal",
        "forced_status",
        "ppo_external",
        "off_campus_external",
        "unattached_external",
        "other_cycle",
    }
