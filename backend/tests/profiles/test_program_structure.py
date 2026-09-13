"""TAX/ELG-2: a programme carries the shape of the enrollment it admits.

Two booleans on the profile could disagree with each other and with the
secondary programme beside them.  A programme cannot: a student is in one, and
"BTech Dual Major" either enrols a second discipline or it does not.
"""

from __future__ import annotations

import os
from typing import cast
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.db import create_engine
from app.core.errors import (
    INVALID_FIELD_VALUE,
    PROGRAM_BRANCH_MISMATCH,
    TAXONOMY_ITEM_NOT_FOUND,
)
from app.domain.pathways import dual_degree_name, dual_major_name
from tests.profiles.conftest import build_test_executor, seed_admin, seed_taxonomy
from tests.profiles.test_profile_commands import _reasons, _run

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("clean_profiles")]


async def _programs(migration: AsyncEngine) -> dict[str, dict[str, object]]:
    async with migration.connect() as connection:
        rows = (
            await connection.execute(
                sa.text(
                    "SELECT name, structure, primary_degree_id, secondary_degree_id "
                    "FROM programs"
                )
            )
        ).mappings().all()
    return {str(row["name"]): dict(row) for row in rows}


async def test_TAX_an_admin_builds_a_dual_degree_out_of_two_plain_degrees() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
        name = dual_degree_name("BTech", "MSc")
        await _run(executor, "upsert_taxonomy_item", {
            "kind": "programs",
            "name": name,
            "structure": "dual_degree",
            "primary_degree_id": str(taxonomy.program_id),
            "secondary_degree_id": str(taxonomy.other_program_id),
        }, admin)
        stored = (await _programs(migration))[name]
        assert stored["structure"] == "dual_degree"
        assert stored["primary_degree_id"] == taxonomy.program_id
        assert stored["secondary_degree_id"] == taxonomy.other_program_id
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_TAX_component_only_edits_are_saved_previewed_and_audited() -> None:
    """Changing a component is a real taxonomy edit, even if structure is stable."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        replacement_degree_id = uuid4()
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
            await connection.execute(
                sa.text(
                    "INSERT INTO programs (id, name, is_active) "
                    "VALUES (:id, 'MSc', true)"
                ),
                {"id": replacement_degree_id},
            )
        payload: dict[str, object] = {
            "kind": "programs",
            "item_id": str(taxonomy.dual_degree_program_id),
            "structure": "dual_degree",
            "primary_degree_id": str(taxonomy.program_id),
            "secondary_degree_id": str(replacement_degree_id),
        }
        command = executor.registry.commands["upsert_taxonomy_item"]
        input_value = command.input_model.model_validate(payload)
        preview = await executor.run(
            "upsert_taxonomy_item", input_value, admin, dry_run=True
        )
        result = await _run(
            executor, "upsert_taxonomy_item", payload, admin
        )
        async with migration.connect() as connection:
            stored = (
                await connection.execute(
                    sa.text(
                        "SELECT primary_degree_id, secondary_degree_id FROM programs "
                        "WHERE id = :id"
                    ),
                    {"id": taxonomy.dual_degree_program_id},
                )
            ).mappings().one()
            audit = (
                await connection.execute(
                    sa.text(
                        "SELECT details FROM audit_log "
                        "WHERE action = 'upsert_taxonomy_item' "
                        "ORDER BY created_at DESC, id DESC LIMIT 1"
                    )
                )
            ).mappings().one()["details"]
    finally:
        await engine.dispose()
        await migration.dispose()

    assert preview.summary == result.summary
    assert result.summary["action"] == "updated"
    assert stored["primary_degree_id"] == taxonomy.program_id
    assert stored["secondary_degree_id"] == replacement_degree_id
    assert audit["before"]["secondary_degree_id"] == str(taxonomy.other_program_id)
    assert audit["after"]["secondary_degree_id"] == str(replacement_degree_id)


async def test_TAX_a_combined_programme_cannot_name_itself_as_a_component() -> None:
    """The command rejects a recursive structure before the database FK sees it."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
        assert await _reasons(executor, "upsert_taxonomy_item", {
            "kind": "programs",
            "item_id": str(taxonomy.dual_degree_program_id),
            "structure": "dual_degree",
            "primary_degree_id": str(taxonomy.dual_degree_program_id),
            "secondary_degree_id": str(taxonomy.other_program_id),
        }, admin) == [(INVALID_FIELD_VALUE, "primary_degree_id")]
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_TAX_a_component_degree_must_exist_and_be_a_plain_degree() -> None:
    """A programme built out of a combined one would describe nothing evaluable."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
        assert await _reasons(executor, "upsert_taxonomy_item", {
            "kind": "programs",
            "name": "Built on nothing",
            "structure": "dual_major",
            "primary_degree_id": str(uuid4()),
            "secondary_degree_id": str(taxonomy.program_id),
        }, admin) == [(TAXONOMY_ITEM_NOT_FOUND, "primary_degree_id")]

        assert await _reasons(executor, "upsert_taxonomy_item", {
            "kind": "programs",
            "name": "Dual major of a dual major",
            "structure": "dual_major",
            "primary_degree_id": str(taxonomy.dual_major_program_id),
            "secondary_degree_id": str(taxonomy.dual_major_program_id),
        }, admin) == [(INVALID_FIELD_VALUE, "primary_degree_id")]
    finally:
        await engine.dispose()
        await migration.dispose()


@pytest.mark.parametrize("structure, primary, secondary", [
    ("single", True, True),
    ("dual_major", True, False),
    ("dual_degree", False, True),
])
async def test_TAX_a_structure_and_its_component_degrees_must_agree(
    structure: str, primary: bool, secondary: bool,
) -> None:
    """Validated before the command runs: the pair is meaningless apart."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            taxonomy = await seed_taxonomy(connection)
        spec = executor.registry.commands["upsert_taxonomy_item"]
        with pytest.raises(ValueError):
            spec.input_model.model_validate({
                "kind": "programs",
                "name": "Disagreeing",
                "structure": structure,
                "primary_degree_id": str(taxonomy.program_id) if primary else None,
                "secondary_degree_id": str(taxonomy.program_id) if secondary else None,
            })
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_TAX_only_a_program_has_a_structure() -> None:
    executor, engine = build_test_executor()
    try:
        spec = executor.registry.commands["upsert_taxonomy_item"]
        with pytest.raises(ValueError):
            spec.input_model.model_validate(
                {"kind": "branches", "name": "Shaped", "structure": "dual_major"}
            )
    finally:
        await engine.dispose()


async def test_TAX_renaming_or_retiring_leaves_the_shape_alone() -> None:
    """A rename that flattened a dual degree would silently rewrite enrollments."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
        renamed = dual_major_name("BTech (revised)")
        await _run(executor, "upsert_taxonomy_item", {
            "kind": "programs",
            "item_id": str(taxonomy.dual_major_program_id),
            "name": renamed,
            "is_active": False,
        }, admin)
        stored = (await _programs(migration))[renamed]
        assert stored["structure"] == "dual_major"
        assert stored["primary_degree_id"] == taxonomy.program_id
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_TAX_a_degree_a_combined_programme_is_built_from_is_not_deleted() -> None:
    """Retiring BTech would leave "BTech Dual Major" describing a missing degree."""
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
        result = await _run(executor, "upsert_taxonomy_item", {
            "kind": "programs",
            "item_id": str(taxonomy.program_id),
            "action": "delete",
        }, admin)
        assert result.summary["action"] == "deactivated"
        async with migration.connect() as connection:
            assert await connection.scalar(
                sa.text("SELECT count(*) FROM programs WHERE id = :id"),
                {"id": taxonomy.program_id},
            ) == 1
    finally:
        await engine.dispose()
        await migration.dispose()


async def test_PRO1_each_discipline_must_belong_to_its_component_degree() -> None:
    """A combined programme's union must not admit a PG branch in the UG slot."""
    from tests.profiles.conftest import seed_student

    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            admin = await seed_admin(connection)
            taxonomy = await seed_taxonomy(connection)
            student = await seed_student(connection, "component-branches@example.edu")
            # CSE belongs only to MTech, while EE belongs only to BTech. The
            # combined programme deliberately retains both in its display union.
            await connection.execute(
                sa.text(
                    "DELETE FROM program_branches "
                    "WHERE (program_id = :btech AND branch_id = :cse) "
                    "OR (program_id = :mtech AND branch_id = :ee)"
                ),
                {
                    "btech": taxonomy.program_id,
                    "mtech": taxonomy.other_program_id,
                    "cse": taxonomy.branch_id,
                    "ee": taxonomy.second_branch_id,
                },
            )
        invalid = await _reasons(executor, "admin_update_profile", {
            "enrollment_id": str(student.enrollment_id),
            "fields": {
                "program_id": str(taxonomy.dual_degree_program_id),
                "primary_branch_id": str(taxonomy.branch_id),
                "secondary_branch_id": str(taxonomy.branch_id),
            },
        }, admin)
        valid = await _run(executor, "admin_update_profile", {
            "enrollment_id": str(student.enrollment_id),
            "fields": {
                "program_id": str(taxonomy.dual_degree_program_id),
                "primary_branch_id": str(taxonomy.second_branch_id),
                "secondary_branch_id": str(taxonomy.branch_id),
            },
        }, admin)
    finally:
        await engine.dispose()
        await migration.dispose()

    assert invalid == [(PROGRAM_BRANCH_MISMATCH, "primary_branch_id")]
    assert valid.summary["changed_fields"] == [
        "primary_branch_id", "program_id", "secondary_branch_id"
    ]


async def test_ELG2_the_profile_form_reads_the_shape_from_the_programme() -> None:
    """`me/profile` carries each programme's structure so the form can ask."""
    from app.modules.profiles.queries import me_profile
    from tests.profiles.conftest import seed_student

    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            taxonomy = await seed_taxonomy(connection)
            student = await seed_student(connection, "shape@example.edu")
        screen = await me_profile(engine, student.enrollment_id)
        programs = {
            str(item["id"]): item
            for item in cast(
                list[dict[str, object]],
                cast(dict[str, object], screen["taxonomies"])["programs"],
            )
        }
        assert programs[str(taxonomy.program_id)]["structure"] == "single"
        assert programs[str(taxonomy.dual_major_program_id)]["structure"] == "dual_major"
        assert (
            programs[str(taxonomy.dual_degree_program_id)]["structure"] == "dual_degree"
        )
    finally:
        await engine.dispose()
        await migration.dispose()
