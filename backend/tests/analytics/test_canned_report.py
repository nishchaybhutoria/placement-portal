"""ANA-3's provisional report, and the honesty its columns are for.

The report is the artefact most likely to be read by somebody who was not in
the room -- pasted into a filing, quoted back a year later -- so what is tested
here is less "the arithmetic works" than "the table cannot be misread": the
flat rate leads, the adjusted rate is labelled, coverage travels beside the
median, and no row is quietly dropped from a denominator.
"""

from __future__ import annotations

import os
from datetime import date
from typing import Any, cast

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.modules.analytics import metrics
from app.modules.analytics.metrics import MetricFilters
from app.modules.analytics.reports import (
    REPORT_COLUMNS,
    batch_report,
    report_rows_for_export,
)
from tests.analytics.conftest import (
    DefinitionWorld,
    build_definition_world,
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


async def _tag(world: DefinitionWorld, key: str, tag: str) -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "UPDATE cycle_memberships SET outcome_tag = CAST(:tag AS outcome_tag_t) "
                    "WHERE cycle_id = :cycle AND enrollment_id = :enrollment"
                ),
                {
                    "tag": tag,
                    "cycle": world.cycle_id,
                    "enrollment": world.enrollment(key),
                },
            )
    finally:
        await engine.dispose()


async def _report(world: DefinitionWorld) -> dict[str, Any]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            labels = {
                str(world.program_id): "BTech",
            }
            return cast(
                "dict[str, Any]",
                await batch_report(
                    connection,
                    MetricFilters(cycle_ids=(world.cycle_id,)),
                    program_labels=labels,
                ),
            )
    finally:
        await engine.dispose()


async def test_ANA3_the_report_says_it_is_provisional(clean_cycles: None) -> None:
    """The office's formats do not exist yet, and the table must admit it."""
    world = await _world()
    report = await _report(world)

    assert report["provisional"] is True
    assert "NIRF" in str(report["note"])
    assert "not available" in str(report["note"])


async def test_ANA3_the_flat_rate_leads_and_the_adjusted_rate_is_labelled(
    clean_cycles: None,
) -> None:
    """Column order is the safeguard: the first rate is the conservative one."""
    keys = [key for key, _label in REPORT_COLUMNS]
    assert keys.index("placement_rate") < keys.index("placement_rate_seeking")
    labels = dict(REPORT_COLUMNS)
    assert labels["placement_rate"] == "Placement rate"
    assert "seeking only" in labels["placement_rate_seeking"]
    # Coverage sits beside the statistics it qualifies, not in a footnote.
    assert keys.index("compensation_covered") > keys.index("median_ctc_lpa")


async def test_ANA3_outcome_tags_build_the_seeking_denominator(
    clean_cycles: None,
) -> None:
    """Tagged members leave the adjusted denominator and only that one."""
    world = await _world()
    await _tag(world, "registered_only", "higher_studies")
    await _tag(world, "applied_only", "not_seeking")
    report = await _report(world)

    total = cast("dict[str, Any]", report["total"])
    assert total["registered"] == 10
    assert total["registered_seeking"] == 8
    assert total["higher_studies"] == 1
    assert total["not_seeking"] == 1
    assert total["entrepreneurship"] == 0
    # The headline rate keeps ANA-1's denominator whatever the tags say.
    assert total["placement_rate"]["denominator"] == 10
    assert total["placement_rate_seeking"]["denominator"] == 8


async def test_ANA3_the_rows_sum_to_the_total_and_to_the_cycle_dashboard(
    clean_cycles: None,
) -> None:
    """No batch is dropped, and the report agrees with the page it came from."""
    world = await _world()
    report = await _report(world)
    rows = cast("list[dict[str, Any]]", report["rows"])
    total = cast("dict[str, Any]", report["total"])

    for column in ("registered", "placed_total", "placed_on_campus", "placed_ppo"):
        assert sum(int(row[column]) for row in rows) == int(total[column]), (
            f"the {column} column must sum to its total: a batch silently "
            "missing from a filing is the failure this report exists to avoid"
        )

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            computed = await metrics.funnel(
                connection, MetricFilters(cycle_ids=(world.cycle_id,))
            )
    finally:
        await engine.dispose()
    assert int(total["placed_total"]) == computed.placed.count
    assert int(total["registered"]) == computed.registered.count


async def test_ANA3_compensation_carries_its_coverage_into_the_report(
    clean_cycles: None,
) -> None:
    world = await _world()
    report = await _report(world)
    total = cast("dict[str, Any]", report["total"])

    assert total["median_ctc_lpa"] == "22.75"
    assert total["mean_ctc_lpa"] == "21.88"
    assert total["compensation_covered"] == 4
    assert int(total["placed_total"]) == 4


async def test_ANA3_a_doubly_placed_student_is_attributed_once_in_the_filing(
    clean_cycles: None,
) -> None:
    """the design review 4.30e binds the canned report, not only dashboards."""
    world = await _world()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            # A later, lower external acceptance for someone already placed on
            # campus proves both halves of the ruling: latest wins, and adding
            # an acceptance does not add a student to the filing.
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

    report = await _report(world)
    rows = [
        *cast("list[dict[str, Any]]", report["rows"]),
        cast("dict[str, Any]", report["total"]),
    ]
    for row in rows:
        source_total = sum(
            int(row[column])
            for column in (
                "placed_on_campus",
                "placed_ppo",
                "placed_off_campus",
                "placed_other_external",
            )
        )
        assert source_total == int(row["placed_total"])
        assert int(row["placed_total"]) == 4

    total = rows[-1]
    assert total["placed_on_campus"] == 1
    assert total["placed_off_campus"] == 2
    assert total["compensation_covered"] == 4
    assert total["mean_ctc_lpa"] == "18.75"


async def test_ANA3_the_export_shape_is_the_screen_shape(clean_cycles: None) -> None:
    """One assembled report behind both surfaces, so they cannot disagree."""
    world = await _world()
    report = await _report(world)
    table = report_rows_for_export(report)

    header = list(table[0])
    assert header == [label for _key, label in REPORT_COLUMNS]
    assert len(table) == len(cast("list[Any]", report["rows"])) + 2, (
        "one header, one row per group, and the total row"
    )
    # A rate exports as its ratio rather than as the object the screen renders.
    rate_column = header.index("Placement rate")
    assert table[-1][rate_column] == "0.4000"
