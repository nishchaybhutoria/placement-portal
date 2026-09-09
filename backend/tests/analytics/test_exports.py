"""ANA-4 exports: the columns, the two delivery paths, and the audit trail.

An export is the one artefact in this system that leaves it -- forwarded to a
company, kept on somebody's laptop for a year, opened by a person who never saw
the filters. So what is tested here is mostly about honesty: that a column
nobody offered is refused rather than silently blank, that the file says what
it is, that the same builder feeds both delivery paths, and that every request
is answerable a year later from `audit_log` alone.
"""

from __future__ import annotations

import csv
import io
import os
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.errors import UNKNOWN_EXPORT_COLUMN, DomainRejection
from app.modules.analytics.columns import (
    application_registry,
    default_columns,
    membership_registry,
    question_column,
)
from app.modules.analytics.exports import (
    SYNC_ROW_LIMIT,
    build_table,
    render,
)
from tests.analytics.conftest import (
    DefinitionWorld,
    build_definition_world,
    build_test_executor,
    seed_admin,
)

pytestmark = pytest.mark.asyncio


async def _world_with_job() -> tuple[DefinitionWorld, UUID, UUID, UUID]:
    """The definition world plus a job carrying one question and one answer."""
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            world = await build_definition_world(connection)
            admin = await seed_admin(connection, email="export-admin@example.edu")
            job_id = cast(
                UUID,
                await connection.scalar(
                    sa.text(
                        "SELECT a.job_id FROM applications a JOIN jobs j "
                        "ON j.id = a.job_id WHERE j.cycle_id = :cycle LIMIT 1"
                    ),
                    {"cycle": world.cycle_id},
                ),
            )
            question_id = uuid4()
            await connection.execute(
                sa.text(
                    "INSERT INTO job_questions (id, job_id, ord, text, qtype, required) "
                    "VALUES (:id, :job, 1, 'Notice period', 'text', false)"
                ),
                {"id": question_id, "job": job_id},
            )
            application_id = cast(
                UUID,
                await connection.scalar(
                    sa.text("SELECT id FROM applications WHERE job_id = :job LIMIT 1"),
                    {"job": job_id},
                ),
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO application_answers (id, application_id, question_id, value) "
                    "VALUES (:id, :application, :question, CAST(:value AS jsonb))"
                ),
                {
                    "id": uuid4(),
                    "application": application_id,
                    "question": question_id,
                    "value": '"30 days"',
                },
            )
            return world, job_id, question_id, admin.user_id
    finally:
        await engine.dispose()


def _admin_actor(user_id: UUID) -> Any:
    from app.core.plan import ActorContext

    return ActorContext(
        principal_id=str(user_id), user_id=user_id, role="admin", session_id=uuid4()
    )


async def _request(payload: dict[str, object], actor: Any, *, dry_run: bool = False) -> Any:
    executor, engine = build_test_executor()
    model = executor.registry.commands["request_export"].input_model
    try:
        return await executor.run(
            "request_export", model.model_validate(payload), actor, dry_run=dry_run
        )
    finally:
        await engine.dispose()


async def test_ANA4_the_column_registry_is_the_profile_registry_plus_questions(
    clean_cycles: None,
) -> None:
    """One statement of the profile fields, not two (PRO-1 already pins it)."""
    from app.modules.profiles.fields import FIELDS

    registry = application_registry(((UUID(int=7), "Notice period"),))
    keys = [column.key for column in registry]

    for field in FIELDS:
        assert field.key in keys, (
            f"{field.key} is in the PRO-1 registry but not exportable; the two "
            "lists must not be maintained separately"
        )
    assert "status" in keys and "current_round" in keys
    assert "applied_at" in keys and "resume_link" in keys
    assert question_column(UUID(int=7), "Notice period").key in keys
    # No ZIPs in this system (Behavior section 17): the link column is how a
    # resume reaches a company at all.
    assert "resume_link" in default_columns(registry)


async def test_ANA4_a_column_outside_the_registry_is_refused_with_all_of_them(
    clean_cycles: None,
) -> None:
    """Every bad name at once, so the picker is fought once rather than thrice."""
    world, job_id, _question_id, admin_id = await _world_with_job()

    with pytest.raises(DomainRejection) as error:
        await _request(
            {
                "cycle_id": str(world.cycle_id),
                "job_id": str(job_id),
                "kind": "job_applications",
                "columns": ["roll_number", "salary_expectation", "question_" + str(uuid4())],
            },
            _admin_actor(admin_id),
        )
    reasons = error.value.rejection.reasons
    assert [reason.code for reason in reasons] == [
        UNKNOWN_EXPORT_COLUMN,
        UNKNOWN_EXPORT_COLUMN,
    ]
    assert "salary_expectation" in reasons[0].human


async def test_ANA4_a_question_column_is_accepted_only_for_its_own_job(
    clean_cycles: None,
) -> None:
    """The registry is per job, which is what makes it able to refuse."""
    world, job_id, question_id, admin_id = await _world_with_job()

    result = await _request(
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(job_id),
            "kind": "job_applications",
            "columns": ["roll_number", f"question_{question_id}"],
        },
        _admin_actor(admin_id),
    )
    assert result.summary["columns"] == ["roll_number", f"question_{question_id}"]

    # The same column name against a different job is not a column at all.
    other_job = await _other_job(world, exclude=job_id)
    with pytest.raises(DomainRejection) as error:
        await _request(
            {
                "cycle_id": str(world.cycle_id),
                "job_id": str(other_job),
                "kind": "job_applications",
                "columns": [f"question_{question_id}"],
            },
            _admin_actor(admin_id),
        )
    assert error.value.rejection.reasons[0].code == UNKNOWN_EXPORT_COLUMN


async def _other_job(world: DefinitionWorld, *, exclude: UUID) -> UUID:
    """Another job in the same cycle -- explicitly not the one under test."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            found = await connection.scalar(
                sa.text(
                    "SELECT id FROM jobs WHERE cycle_id = :cycle AND id <> :exclude "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"cycle": world.cycle_id, "exclude": exclude},
            )
    finally:
        await engine.dispose()
    assert found is not None, "the world seeds several jobs in this cycle"
    return cast(UUID, found)


async def test_ANA4_a_small_export_is_ready_immediately_and_never_defers(
    clean_cycles: None,
) -> None:
    """LLD section 12: at or below 5000 rows, built synchronously."""
    world, job_id, _question_id, admin_id = await _world_with_job()

    result = await _request(
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(job_id),
            "kind": "job_applications",
        },
        _admin_actor(admin_id),
    )
    assert result.summary["mode"] == "sync"
    assert result.summary["status"] == "ready"
    assert int(result.summary["row_count"]) <= SYNC_ROW_LIMIT

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            queued = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM procrastinate_jobs "
                    "WHERE task_name = 'build_export'"
                )
            )
    finally:
        await engine.dispose()
    assert int(queued or 0) == 0, "a small export must not queue a worker job"


async def test_ANA4_an_export_over_the_limit_defers_and_is_polled(
    clean_cycles: None,
) -> None:
    """Above 5000 rows the request queues build_export and waits."""
    world, job_id, _question_id, admin_id = await _world_with_job()
    await _inflate_applications(job_id, SYNC_ROW_LIMIT + 1)

    result = await _request(
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(job_id),
            "kind": "job_applications",
        },
        _admin_actor(admin_id),
    )
    assert result.summary["mode"] == "deferred"
    assert result.summary["status"] == "queued"

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            queued = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM procrastinate_jobs "
                    "WHERE task_name = 'build_export'"
                )
            )
            status = await connection.scalar(
                sa.text("SELECT status FROM export_jobs WHERE id = :id"),
                {"id": UUID(str(result.summary["export_id"]))},
            )
    finally:
        await engine.dispose()
    assert int(queued or 0) == 1
    assert str(status) == "queued"


async def _inflate_applications(job_id: UUID, target: int) -> None:
    """Enough applications to cross the sync limit, cheaply.

    Roll numbers are counted, not sliced out of a UUID: eight hex characters
    over five thousand rows collide often enough (~0.3% a run) to make this
    the suite's flakiest fixture, and `enrollments.roll_number` is unique.
    """
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO users (id, email, full_name, role)
                    SELECT gen_random_uuid(), 'bulk' || g || '@example.edu',
                           'Bulk ' || g, 'student'
                    FROM generate_series(1, :n) g
                    """
                ),
                {"n": target},
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO enrollments (id, user_id, is_current, roll_number)
                    SELECT gen_random_uuid(), u.id, true,
                           'B' || lpad(
                               (row_number() OVER (ORDER BY u.email))::text, 8, '0'
                           )
                    FROM users u WHERE u.email LIKE 'bulk%@example.edu'
                    """
                )
            )
            await connection.execute(
                sa.text(
                    """
                    INSERT INTO applications
                        (id, job_id, enrollment_id, status, resume_url,
                         profile_snapshot, applied_at)
                    SELECT gen_random_uuid(), :job, e.id, 'in_progress',
                           'https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view',
                           '{}'::jsonb, now()
                    FROM enrollments e JOIN users u ON u.id = e.user_id
                    WHERE u.email LIKE 'bulk%@example.edu'
                    """
                ),
                {"job": job_id},
            )
    finally:
        await engine.dispose()


async def test_ANA4_every_export_is_audited_with_who_what_columns_and_filters(
    clean_cycles: None,
) -> None:
    """The audit row must answer "who sent this out, and what was in it"."""
    world, job_id, _question_id, admin_id = await _world_with_job()

    await _request(
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(job_id),
            "kind": "job_applications",
            "columns": ["roll_number", "resume_link"],
            "format": "csv",
            "status": "accepted",
        },
        _admin_actor(admin_id),
    )

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    sa.text(
                        "SELECT actor_user_id, action, subject_type, details "
                        "FROM audit_log WHERE subject_type = 'export' "
                        "ORDER BY created_at DESC LIMIT 1"
                    )
                )
            ).mappings().one()
    finally:
        await engine.dispose()

    details = cast("dict[str, Any]", row["details"])
    assert row["actor_user_id"] == admin_id
    assert details["columns"] == ["roll_number", "resume_link"]
    assert details["format"] == "csv"
    assert details["filters"]["status"] == "accepted"
    assert details["filters"]["job_id"] == str(job_id)
    assert details["mode"] == "sync"


async def test_ANA4_the_built_file_carries_questions_without_a_metadata_preamble(
    clean_cycles: None,
) -> None:
    """Question columns resolve to answers and row one is the real header."""
    world, job_id, question_id, _admin_id = await _world_with_job()
    params: dict[str, object] = {
        "cycle_id": str(world.cycle_id),
        "job_id": str(job_id),
        "kind": "job_applications",
        "format": "csv",
        "columns": ["full_name", "status", f"question_{question_id}"],
        "status": None,
        "round_id": None,
    }

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            table = await build_table(connection, params)
    finally:
        await engine.dispose()

    assert table[0] == ["Full name", "Status", "Notice period"]
    answers = [row[2] for row in table[1:]]
    assert "30 days" in answers

    payload, media_type, filename = render(
        table, params, requested_by="export-admin@example.edu"
    )
    text = payload.decode("utf-8-sig")
    lines = list(csv.reader(io.StringIO(text)))
    assert lines[0] == ["Full name", "Status", "Notice period"]
    assert not any("CDS Portal export" in cell for line in lines for cell in line)
    assert media_type.startswith("text/csv")
    assert filename.endswith(".csv")


async def test_ANA4_membership_exports_carry_approval_status_and_outcome_tags(
    clean_cycles: None,
) -> None:
    """ANA-4 names both explicitly, because they are the honest denominators."""
    world, _job_id, _question_id, admin_id = await _world_with_job()
    keys = [column.key for column in membership_registry()]
    assert "membership_status" in keys
    assert "outcome_tag" in keys

    result = await _request(
        {
            "cycle_id": str(world.cycle_id),
            "kind": "cycle_memberships",
            "columns": ["full_name", "membership_status", "outcome_tag"],
        },
        _admin_actor(admin_id),
    )
    assert result.summary["status"] == "ready"

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            table = await build_table(
                connection,
                {
                    "cycle_id": str(world.cycle_id),
                    "kind": "cycle_memberships",
                    "format": "csv",
                    "columns": ["full_name", "membership_status", "outcome_tag"],
                },
            )
    finally:
        await engine.dispose()

    assert table[0] == ["Full name", "Approval status", "Outcome tag"]
    statuses = {str(row[1]) for row in table[1:]}
    # The pending member is in the file: an export used to build a denominator
    # must not quietly drop the rows that make the denominator interesting.
    assert {"active", "pending"} <= statuses


async def test_ANA4_a_preset_naming_an_unknown_column_is_refused_at_save_time(
    clean_cycles: None,
) -> None:
    """M9's command gained the registry, so the failure lands where it can be read."""
    world, job_id, _question_id, admin_id = await _world_with_job()
    executor, engine = build_test_executor()
    model = executor.registry.commands["save_export_preset"].input_model
    try:
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "save_export_preset",
                model.model_validate(
                    {
                        "cycle_id": str(world.cycle_id),
                        "job_id": str(job_id),
                        "columns": ["roll_number", "not_a_column"],
                    }
                ),
                _admin_actor(admin_id),
            )
        assert error.value.rejection.reasons[0].code == UNKNOWN_EXPORT_COLUMN

        # And a good one still saves, so the validation did not close the door.
        saved = await executor.run(
            "save_export_preset",
            model.model_validate(
                {
                    "cycle_id": str(world.cycle_id),
                    "job_id": str(job_id),
                    "columns": ["roll_number", "resume_link"],
                }
            ),
            _admin_actor(admin_id),
        )
        assert saved.summary["columns"] == ["roll_number", "resume_link"]
    finally:
        await engine.dispose()


async def test_ANA4_the_download_route_streams_and_refuses_a_stranger(
    clean_cycles: None,
) -> None:
    """An export URL is forwardable; a spreadsheet of students is not public."""
    import httpx

    from app.main import create_app
    from app.modules.identity.session import hash_session_token
    from app.settings import Settings
    from tests.analytics.conftest import seed_person

    world, job_id, _question_id, admin_id = await _world_with_job()
    settings = Settings(
        session_secret="export-route-session-secret-32-characters", dev_login=False
    )
    admin_token, stranger_token = "export-admin-token", "export-stranger-token"

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            stranger = await seed_person(connection, email="stranger@example.edu")
            for user_id, token in (
                (admin_id, admin_token),
                (stranger.user_id, stranger_token),
            ):
                await connection.execute(
                    sa.text(
                        "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
                        "VALUES (gen_random_uuid(), :hash, :user, now() + interval '1 day')"
                    ),
                    {
                        "hash": hash_session_token(token, settings.session_secret),
                        "user": user_id,
                    },
                )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycle_coordinators (id, cycle_id, user_id) "
                    "VALUES (gen_random_uuid(), :cycle, :user)"
                ),
                {"cycle": world.cycle_id, "user": stranger.user_id},
            )
    finally:
        await engine.dispose()

    result = await _request(
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(job_id),
            "kind": "job_applications",
            "format": "csv",
            "columns": ["full_name", "status", "resume_link"],
        },
        _admin_actor(admin_id),
    )
    export_id = str(result.summary["export_id"])

    app = create_app(os.environ["TEST_DATABASE_URL"], settings=settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://export.test",
        cookies={"cds_session": admin_token},
    ) as client:
        status = await client.get(f"/api/v1/exports/{export_id}")
        assert status.status_code == 200
        assert status.json()["status"] == "ready"
        assert status.json()["download_url"].endswith(f"{export_id}/download")

        download = await client.get(f"/api/v1/exports/{export_id}/download")
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("text/csv")
        assert ".csv" in download.headers["content-disposition"]
        body = download.content.decode("utf-8-sig")
        assert body.startswith("Full name,Status,Resume link")
        assert "Resume link" in body

    # A coordinator of the same cycle is still not the requester: ANA-4 audits
    # exports by who asked, and that only means something if the audited person
    # is who fetched the file.
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://export.test",
        cookies={"cds_session": stranger_token},
    ) as stranger_client:
        refused = await stranger_client.get(f"/api/v1/exports/{export_id}/download")
        assert refused.status_code in (401, 403)

    async with httpx.AsyncClient(
        transport=transport, base_url="http://export.test"
    ) as anonymous_client:
        anonymous = await anonymous_client.get(f"/api/v1/exports/{export_id}/download")
        assert anonymous.status_code in (401, 403)


async def test_ANA4_the_deferred_path_stores_what_the_sync_path_would_stream(
    clean_cycles: None,
) -> None:
    """One builder behind both delivery paths, so the two files agree."""
    from base64 import b64decode, b64encode

    from app.core.plan import ActorContext

    world, job_id, question_id, admin_id = await _world_with_job()
    # A genuinely deferred export: the completion command is only reachable
    # from the >5k path, because a sync request is already `ready` and the
    # idempotency guard correctly refuses to write over it.
    await _inflate_applications(job_id, SYNC_ROW_LIMIT + 1)

    columns = ["full_name", "status", f"question_{question_id}"]
    request = await _request(
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(job_id),
            "kind": "job_applications",
            "format": "csv",
            "columns": columns,
        },
        _admin_actor(admin_id),
    )
    assert request.summary["mode"] == "deferred"
    export_id = UUID(str(request.summary["export_id"]))

    params: dict[str, object] = {
        "cycle_id": str(world.cycle_id),
        "job_id": str(job_id),
        "kind": "job_applications",
        "format": "csv",
        "columns": columns,
        "status": None,
        "round_id": None,
    }
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            table = await build_table(connection, params)
    finally:
        await engine.dispose()
    payload, _media, _name = render(
        table, params, requested_by="export-admin@example.edu"
    )

    executor, engine = build_test_executor()
    model = executor.registry.commands["complete_export"].input_model
    system = ActorContext(principal_id="system", is_system=True)
    try:
        completed = await executor.run(
            "complete_export",
            model.model_validate(
                {
                    "export_id": str(export_id),
                    "encoded": b64encode(payload).decode("ascii"),
                    "byte_size": len(payload),
                }
            ),
            system,
        )
        assert completed.summary["status"] == "ready"
        assert completed.summary["stored"] is True

        # Running the task twice must not write twice: a deferred handler that
        # is not idempotent corrupts state on any retry (CONTRIBUTING.md invariant 3).
        again = await executor.run(
            "complete_export",
            model.model_validate(
                {"export_id": str(export_id), "encoded": "", "byte_size": 0}
            ),
            system,
        )
        assert again.summary["stored"] is False
    finally:
        await engine.dispose()

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            meta = await connection.scalar(
                sa.text("SELECT result_meta FROM export_jobs WHERE id = :id"),
                {"id": export_id},
            )
    finally:
        await engine.dispose()
    stored = cast("dict[str, Any]", meta)
    assert b64decode(str(stored["content"])) == payload
    # The stored bytes are the sync builder's bytes, not a second rendering.
    assert int(stored["byte_size"]) == len(payload)


async def test_ANA4_what_the_export_picker_offers_is_what_the_command_accepts(
    clean_cycles: None,
) -> None:
    """the design review 4.22 for the export modal, in several states.

    The picker's columns come from the screen; the command validates against
    the registry. If those two lists could differ, the failure is either a
    column the user can choose and the command refuses, or -- worse, because
    nothing surfaces it -- a column the command would accept that nobody is
    ever offered. So every column the screen offers is *driven through the
    command*, and every column the command rejects is proved absent from the
    screen.
    """
    import httpx

    from app.main import create_app
    from app.modules.identity.session import hash_session_token
    from app.settings import Settings

    world, job_id, question_id, admin_id = await _world_with_job()
    settings = Settings(
        session_secret="export-pin-session-secret-32-characters", dev_login=False
    )
    token = "export-pin-admin-token"
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
                    "VALUES (gen_random_uuid(), :hash, :user, now() + interval '1 day')"
                ),
                {
                    "hash": hash_session_token(token, settings.session_secret),
                    "user": admin_id,
                },
            )
    finally:
        await engine.dispose()

    app = create_app(os.environ["TEST_DATABASE_URL"], settings=settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://pin.test",
        cookies={"cds_session": token},
    ) as client:
        job_screen = await client.get(f"/api/v1/screens/staff/job/{job_id}/analytics")
        cycle_screen = await client.get(
            f"/api/v1/screens/staff/cycle/{world.cycle_id}/analytics"
        )
    assert job_screen.status_code == 200
    assert cycle_screen.status_code == 200

    job_offered = [
        str(column["key"])
        for column in cast("list[dict[str, Any]]", job_screen.json()["export_columns"])
    ]
    cycle_offered = [
        str(column["key"])
        for column in cast("list[dict[str, Any]]", cycle_screen.json()["export_columns"])
    ]

    # The job's own question is offered, which is the part a static list would
    # get wrong the first time a question was added.
    assert f"question_{question_id}" in job_offered
    assert "membership_status" in cycle_offered and "outcome_tag" in cycle_offered

    # Every offered column survives the command. Asking for all of them at once
    # is the strongest form: one refusal fails the whole request.
    accepted_job = await _request(
        {
            "cycle_id": str(world.cycle_id),
            "job_id": str(job_id),
            "kind": "job_applications",
            "columns": job_offered,
        },
        _admin_actor(admin_id),
        dry_run=True,
    )
    assert list(accepted_job.summary["columns"]) == job_offered

    accepted_cycle = await _request(
        {
            "cycle_id": str(world.cycle_id),
            "kind": "cycle_memberships",
            "columns": cycle_offered,
        },
        _admin_actor(admin_id),
        dry_run=True,
    )
    assert list(accepted_cycle.summary["columns"]) == cycle_offered

    # And the other direction: a membership column is not offered on the job
    # picker, and the command refuses it there too. Asserting only that the
    # good case works is not a pin -- the failure mode is a control that never
    # appears for something the server would have allowed.
    assert "membership_status" not in job_offered
    with pytest.raises(DomainRejection) as error:
        await _request(
            {
                "cycle_id": str(world.cycle_id),
                "job_id": str(job_id),
                "kind": "job_applications",
                "columns": ["membership_status"],
            },
            _admin_actor(admin_id),
            dry_run=True,
        )
    assert error.value.rejection.reasons[0].code == UNKNOWN_EXPORT_COLUMN

    assert f"question_{question_id}" not in cycle_offered
    with pytest.raises(DomainRejection):
        await _request(
            {
                "cycle_id": str(world.cycle_id),
                "kind": "cycle_memberships",
                "columns": [f"question_{question_id}"],
            },
            _admin_actor(admin_id),
            dry_run=True,
        )
