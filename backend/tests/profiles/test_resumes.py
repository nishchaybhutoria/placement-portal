"""Resume library shape rules, default handling, and deletion (PRO-3)."""

from __future__ import annotations

import os
from typing import cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import (
    INVALID_DRIVE_URL,
    LAST_RESUME,
    RESUME_NOT_FOUND,
    DomainRejection,
)
from app.core.executor import Executor
from app.core.plan import Result
from app.modules.profiles.commands import is_drive_file_url
from tests.profiles.conftest import (
    DRIVE_URL,
    OTHER_DRIVE_URL,
    Student,
    build_test_executor,
    seed_student,
)

pytestmark = pytest.mark.usefixtures("clean_profiles")


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view",
        "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view?usp=sharing",
        "https://drive.google.com/open?id=1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/edit",
        "https://docs.google.com/spreadsheets/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/edit#gid=0",
        "https://docs.google.com/presentation/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/preview",
    ],
)
def test_PRO3_drive_file_links_are_accepted(url: str) -> None:
    assert is_drive_file_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz012345",
        "https://example.com/resume.pdf",
        "http://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view",
        "https://drive.google.com/file/d/short/view",
        "https://drive.evil.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view",
        "drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view",
        "javascript:alert(1)",
        "",
    ],
)
def test_PRO3_arbitrary_links_are_rejected(url: str) -> None:
    assert not is_drive_file_url(url)


async def _add(
    executor: Executor, student: Student, label: str, url: str = DRIVE_URL, **extra: object
) -> UUID:
    spec = executor.registry.commands["add_resume"]
    result = await executor.run(
        "add_resume",
        spec.input_model.model_validate(
            {
                "enrollment_id": str(student.enrollment_id),
                "label": label,
                "drive_url": url,
                **extra,
            }
        ),
        student.actor,
    )
    assert isinstance(result, Result)
    return UUID(cast(str, result.summary["resume_id"]))


async def _command(
    executor: Executor, name: str, payload: dict[str, object], student: Student
) -> Result:
    spec = executor.registry.commands[name]
    result = await executor.run(name, spec.input_model.model_validate(payload), student.actor)
    assert isinstance(result, Result)
    return result


@pytest.mark.asyncio
async def test_PRO3_first_resume_becomes_the_default_and_the_flip_is_atomic() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "resume@example.edu")
        first = await _add(executor, student, "Primary")
        second = await _add(executor, student, "Secondary", OTHER_DRIVE_URL)
        await _command(
            executor,
            "set_default_resume",
            {"enrollment_id": str(student.enrollment_id), "resume_id": str(second)},
            student,
        )
        unchanged = await _command(
            executor,
            "set_default_resume",
            {"enrollment_id": str(student.enrollment_id), "resume_id": str(second)},
            student,
        )
        async with migration.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text("SELECT id, is_default FROM resumes ORDER BY created_at")
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert [(row["id"], row["is_default"]) for row in rows] == [
        (first, False),
        (second, True),
    ]
    assert unchanged.summary["changed"] is False


@pytest.mark.asyncio
async def test_PRO3_saving_validates_url_shape_only() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "shape@example.edu")
        spec = executor.registry.commands["add_resume"]
        with pytest.raises(DomainRejection) as rejection:
            await executor.run(
                "add_resume",
                spec.input_model.model_validate(
                    {
                        "enrollment_id": str(student.enrollment_id),
                        "label": "Bad",
                        "drive_url": "https://example.com/resume.pdf",
                    }
                ),
                student.actor,
            )
        resume_id = await _add(executor, student, "Good")
        with pytest.raises(DomainRejection) as edit_rejection:
            await _command(
                executor,
                "update_resume",
                {
                    "enrollment_id": str(student.enrollment_id),
                    "resume_id": str(resume_id),
                    "drive_url": "https://example.com/other.pdf",
                },
                student,
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert [reason.code for reason in rejection.value.rejection.reasons] == [INVALID_DRIVE_URL]
    assert [reason.code for reason in edit_rejection.value.rejection.reasons] == [
        INVALID_DRIVE_URL
    ]


@pytest.mark.asyncio
async def test_PRO3_deleting_the_only_resume_is_rejected() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "single@example.edu")
        resume_id = await _add(executor, student, "Only")
        with pytest.raises(DomainRejection) as rejection:
            await _command(
                executor,
                "delete_resume",
                {"enrollment_id": str(student.enrollment_id), "resume_id": str(resume_id)},
                student,
            )
        async with migration.connect() as connection:
            remaining = await connection.scalar(sa.text("SELECT count(*) FROM resumes"))
    finally:
        await engine.dispose()
        await migration.dispose()

    assert [reason.code for reason in rejection.value.rejection.reasons] == [LAST_RESUME]
    assert remaining == 1


@pytest.mark.asyncio
async def test_PRO3_deleting_the_default_promotes_the_newest_remaining_resume() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "promote@example.edu")
        default_resume = await _add(executor, student, "Primary")
        middle = await _add(executor, student, "Middle", OTHER_DRIVE_URL)
        newest = await _add(executor, student, "Newest", OTHER_DRIVE_URL)
        result = await _command(
            executor,
            "delete_resume",
            {"enrollment_id": str(student.enrollment_id), "resume_id": str(default_resume)},
            student,
        )
        async with migration.connect() as connection:
            rows = (
                await connection.execute(
                    sa.text("SELECT id, is_default FROM resumes ORDER BY created_at")
                )
            ).mappings().all()
    finally:
        await engine.dispose()
        await migration.dispose()

    assert result.summary["promoted_resume_id"] == str(newest)
    assert [(row["id"], row["is_default"]) for row in rows] == [
        (middle, False),
        (newest, True),
    ]


@pytest.mark.asyncio
async def test_PRO3_deleting_a_resume_clears_membership_defaults_with_a_warning() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "membership@example.edu")
        used = await _add(executor, student, "Used")
        keeper = await _add(executor, student, "Keeper", OTHER_DRIVE_URL)
        cycle_id = uuid4()
        async with migration.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO cycles (id, name, kind, is_active) "
                    "VALUES (:id, 'Placement 2026', 'placement', true)"
                ),
                {"id": cycle_id},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_memberships "
                    "(cycle_id, enrollment_id, status, default_resume_id) "
                    "VALUES (:cycle, :enrollment, 'active', :resume)"
                ),
                {"cycle": cycle_id, "enrollment": student.enrollment_id, "resume": used},
            )
        result = await _command(
            executor,
            "delete_resume",
            {"enrollment_id": str(student.enrollment_id), "resume_id": str(used)},
            student,
        )
        async with migration.connect() as connection:
            membership_default = await connection.scalar(
                sa.text("SELECT default_resume_id FROM cycle_memberships")
            )
    finally:
        await engine.dispose()
        await migration.dispose()

    assert result.summary["memberships_default_cleared"] == 1
    assert result.summary["promoted_resume_id"] == str(keeper)
    assert membership_default is None


@pytest.mark.asyncio
async def test_PRO3_unknown_resume_ids_are_rejected() -> None:
    executor, engine = build_test_executor()
    migration = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration.begin() as connection:
            student = await seed_student(connection, "missing@example.edu")
        with pytest.raises(DomainRejection) as rejection:
            await _command(
                executor,
                "set_default_resume",
                {"enrollment_id": str(student.enrollment_id), "resume_id": str(uuid4())},
                student,
            )
    finally:
        await engine.dispose()
        await migration.dispose()
    assert [reason.code for reason in rejection.value.rejection.reasons] == [RESUME_NOT_FOUND]
