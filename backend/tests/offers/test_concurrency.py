"""Real PostgreSQL races for the enrollment mutex and cap guard."""

from __future__ import annotations

import asyncio
import os
from dataclasses import replace
from typing import cast
from uuid import UUID

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.executor import Executor
from app.core.plan import Result
from app.core.registry import Loader
from tests.offers.conftest import (
    build_test_executor,
    seed_admin,
    seed_application,
    seed_cycle,
    seed_external_offer,
    seed_job,
    seed_person,
    seed_portal_offer,
)

pytestmark = pytest.mark.asyncio


class _TransactionBarrier:
    """Hold command loaders until two distinct PostgreSQL backends arrive."""

    def __init__(self) -> None:
        self.arrivals = 0
        self.backend_pids: set[int] = set()
        self.ready = asyncio.Event()

    async def arrive(self, tx: AsyncSession) -> None:
        backend_pid = await tx.scalar(sa.text("SELECT pg_backend_pid()"))
        assert isinstance(backend_pid, int)
        self.backend_pids.add(backend_pid)
        self.arrivals += 1
        if self.arrivals == 2:
            self.ready.set()
        await asyncio.wait_for(self.ready.wait(), timeout=5)

    def assert_real_parallelism(self) -> None:
        assert self.arrivals == 2
        assert len(self.backend_pids) == 2


def _with_loader_barrier(executor: Executor, command_names: tuple[str, str]) -> _TransactionBarrier:
    """Synchronize two real command transactions immediately before loading."""
    barrier = _TransactionBarrier()

    def wrapped(loader: Loader) -> Loader:
        async def synchronize(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> object:
            await barrier.arrive(tx)
            return await loader(tx, input_value, lock=lock)

        return synchronize

    for command_name in set(command_names):
        spec = executor.registry.commands[command_name]
        executor.registry.commands[command_name] = replace(spec, loader=wrapped(spec.loader))
    return barrier


async def test_OFR3_parallel_open_accepts_with_cap_one_have_exactly_one_winner() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection, kind="open")
            await connection.execute(
                sa.text("UPDATE cycle_policies SET max_accepted_offers = 1 WHERE cycle_id = :id"),
                {"id": cycle_id},
            )
            placement_job = await seed_job(
                connection,
                cycle_id=cycle_id,
                title="Open placement",
                outcome="placement",
                with_deadline=False,
            )
            internship_job = await seed_job(
                connection,
                cycle_id=cycle_id,
                title="Open internship",
                outcome="internship",
                with_deadline=False,
            )
            placement_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                job_id=placement_job,
            )
            internship_application, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                job_id=internship_job,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    barrier = _with_loader_barrier(executor, ("record_open_outcome", "record_open_outcome"))

    async def record(job_id: UUID, application_id: UUID, key: str) -> Result:
        result = await executor.run_bulk(
            "record_open_outcome",
            [{"application_id": str(application_id)}],
            key,
            admin.actor,
            batch_fields={
                "cycle_id": cycle_id,
                "job_id": job_id,
                "target_status": "accepted",
            },
        )
        assert isinstance(result, Result)
        return result

    try:
        placement_result, internship_result = await asyncio.gather(
            record(placement_job, placement_application, "cap-placement"),
            record(internship_job, internship_application, "cap-internship"),
        )
    finally:
        await command_engine.dispose()

    placement_rows = cast("list[dict[str, object]]", placement_result.summary["rows"])
    internship_rows = cast("list[dict[str, object]]", internship_result.summary["rows"])
    barrier.assert_real_parallelism()
    rows = [placement_rows[0], internship_rows[0]]
    assert [row["status"] for row in rows].count("ok") == 1
    assert [row["reason"] for row in rows].count("offer_cap_reached") == 1

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            accepted = await connection.scalar(
                sa.text(
                    "SELECT count(*) FROM applications WHERE id = ANY(:ids) AND status = 'accepted'"
                ),
                {"ids": [placement_application, internship_application]},
            )
    finally:
        await engine.dispose()
    assert accepted == 1


async def test_OFR3_parallel_accept_and_decline_do_not_invert_offer_application_locks() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job_id,
            )
            offer_id = await seed_portal_offer(connection, application_id=application_id)
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    barrier = _with_loader_barrier(executor, ("accept_offer", "decline_offer"))
    spec = executor.registry.commands["accept_offer"]
    input_value = spec.input_model.model_validate(
        {
            "cycle_id": cycle_id,
            "job_id": job_id,
            "application_id": application_id,
            "offer_id": offer_id,
            "enrollment_id": student.enrollment_id,
            "expected_status": "offered",
        }
    )

    async def respond(command: str) -> object:
        try:
            return await executor.run(command, input_value, student.actor)
        except DomainRejection as error:
            return error

    try:
        outcomes = await asyncio.wait_for(
            asyncio.gather(respond("accept_offer"), respond("decline_offer")),
            timeout=5,
        )
    finally:
        await command_engine.dispose()

    barrier.assert_real_parallelism()
    assert sum(isinstance(outcome, Result) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, DomainRejection) for outcome in outcomes) == 1


async def test_OFR3_accept_and_job_cancellation_share_offer_then_application_order() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job_id,
            )
            offer_id = await seed_portal_offer(connection, application_id=application_id)
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    barrier = _with_loader_barrier(executor, ("accept_offer", "cancel_job"))
    accept_spec = executor.registry.commands["accept_offer"]
    accept_input = accept_spec.input_model.model_validate(
        {
            "cycle_id": cycle_id,
            "job_id": job_id,
            "application_id": application_id,
            "offer_id": offer_id,
            "enrollment_id": student.enrollment_id,
            "expected_status": "offered",
        }
    )

    async def accept() -> object:
        try:
            return await executor.run("accept_offer", accept_input, student.actor)
        except DomainRejection as error:
            return error

    async def cancel() -> Result:
        result = await executor.run_bulk(
            "cancel_job",
            [{"application_id": str(application_id)}],
            "cancel-accept-race",
            admin.actor,
            batch_fields={
                "cycle_id": cycle_id,
                "job_id": job_id,
                "reason": "Company cancelled",
            },
        )
        assert isinstance(result, Result)
        return result

    try:
        await asyncio.wait_for(asyncio.gather(accept(), cancel()), timeout=5)
    finally:
        await command_engine.dispose()

    barrier.assert_real_parallelism()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            row = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT a.status, o.response, o.terminated_at "
                            "FROM applications a JOIN offers o ON o.application_id = a.id "
                            "WHERE a.id = :id"
                        ),
                        {"id": application_id},
                    )
                )
                .mappings()
                .one()
            )
    finally:
        await engine.dispose()
    if row["status"] == "accepted":
        assert row["response"] == "accepted" and row["terminated_at"] is None
    else:
        assert row["status"] == "rejected" and row["terminated_at"] is not None


async def test_EXT4_portal_accept_and_external_accept_race_on_one_real_mutex() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="channel-race@example.edu")
            cycle_id = await seed_cycle(connection)
            job_id = await seed_job(connection, cycle_id=cycle_id)
            company_id = await connection.scalar(
                sa.text("SELECT company_id FROM jobs WHERE id = :id"),
                {"id": job_id},
            )
            assert isinstance(company_id, UUID)
            application_id, _ = await seed_application(
                connection,
                cycle_id=cycle_id,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=job_id,
            )
            offer_id = await seed_portal_offer(connection, application_id=application_id)
            external_offer_id = await seed_external_offer(
                connection,
                enrollment_id=student.enrollment_id,
                company_id=company_id,
                created_by=admin.user_id,
            )
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    barrier = _with_loader_barrier(executor, ("accept_offer", "update_external_offer"))

    async def portal_accept() -> object:
        spec = executor.registry.commands["accept_offer"]
        try:
            return await executor.run(
                "accept_offer",
                spec.input_model.model_validate(
                    {
                        "cycle_id": cycle_id,
                        "job_id": job_id,
                        "application_id": application_id,
                        "offer_id": offer_id,
                        "enrollment_id": student.enrollment_id,
                        "expected_status": "offered",
                    }
                ),
                student.actor,
            )
        except DomainRejection as error:
            return error

    async def external_accept() -> object:
        spec = executor.registry.commands["update_external_offer"]
        try:
            return await executor.run(
                "update_external_offer",
                spec.input_model.model_validate(
                    {
                        "external_offer_id": external_offer_id,
                        "expected_status": "offered",
                        "status": "accepted",
                        "reason": "Acceptance confirmed",
                    }
                ),
                admin.actor,
            )
        except DomainRejection as error:
            return error

    try:
        outcomes = await asyncio.wait_for(
            asyncio.gather(portal_accept(), external_accept()), timeout=5
        )
    finally:
        await command_engine.dispose()

    barrier.assert_real_parallelism()
    assert sum(isinstance(outcome, Result) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, DomainRejection) for outcome in outcomes) == 1

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            portal = await connection.scalar(
                sa.text("SELECT status FROM applications WHERE id = :id"),
                {"id": application_id},
            )
            external = await connection.scalar(
                sa.text("SELECT status FROM external_offers WHERE id = :id"),
                {"id": external_offer_id},
            )
    finally:
        await engine.dispose()
    assert (portal == "accepted") != (external == "accepted")


async def test_OFR3_cross_cycle_parallel_placement_accepts_share_one_mutex() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_admin(connection)
            student = await seed_person(connection, email="student@example.edu")
            first_cycle = await seed_cycle(connection, name="Placement A")
            second_cycle = await seed_cycle(connection, name="Placement B")
            first_job = await seed_job(connection, cycle_id=first_cycle, title="Placement A role")
            second_job = await seed_job(connection, cycle_id=second_cycle, title="Placement B role")
            first_application, _ = await seed_application(
                connection,
                cycle_id=first_cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=first_job,
            )
            second_application, _ = await seed_application(
                connection,
                cycle_id=second_cycle,
                enrollment_id=student.enrollment_id,
                status="offered",
                job_id=second_job,
            )
            first_offer = await seed_portal_offer(connection, application_id=first_application)
            second_offer = await seed_portal_offer(connection, application_id=second_application)
    finally:
        await engine.dispose()

    executor, command_engine = build_test_executor()
    barrier = _with_loader_barrier(executor, ("accept_offer", "accept_offer"))

    async def accept(cycle_id: UUID, job_id: UUID, application_id: UUID, offer_id: UUID) -> object:
        spec = executor.registry.commands["accept_offer"]
        try:
            return await executor.run(
                "accept_offer",
                spec.input_model.model_validate(
                    {
                        "cycle_id": cycle_id,
                        "job_id": job_id,
                        "application_id": application_id,
                        "offer_id": offer_id,
                        "enrollment_id": student.enrollment_id,
                        "expected_status": "offered",
                    }
                ),
                student.actor,
            )
        except DomainRejection as error:
            return error

    try:
        outcomes = await asyncio.gather(
            accept(first_cycle, first_job, first_application, first_offer),
            accept(second_cycle, second_job, second_application, second_offer),
        )
    finally:
        await command_engine.dispose()

    barrier.assert_real_parallelism()
    assert sum(isinstance(outcome, Result) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, DomainRejection) for outcome in outcomes) == 1

    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            rows = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT status, count(*) AS count FROM applications "
                            "WHERE id = ANY(:ids) GROUP BY status"
                        ),
                        {"ids": [first_application, second_application]},
                    )
                )
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()
    assert {row["status"]: row["count"] for row in rows} == {
        "accepted": 1,
        "declined": 1,
    }
