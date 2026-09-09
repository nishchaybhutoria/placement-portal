"""M2 executor guarantees for Behavior section 16 and LLD section 5."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import create_engine
from app.core.errors import IDEMPOTENCY_CONFLICT, DomainRejection
from app.core.executor import Executor, ExecutorHooks
from app.core.plan import (
    ActorContext,
    Deferred,
    LoadedState,
    Plan,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import CommandSpec, Registry


class PingInput(BaseModel):
    recipient: str = "student@example.edu"
    schedule_at: datetime | None = None


class PingSummary(BaseModel):
    accepted: bool


class DeleteNotificationInput(BaseModel):
    id: UUID


class DeleteNotificationSummary(BaseModel):
    deleted: bool


DELETE_NOTIFICATION_ID = UUID("00000000-0000-0000-0000-000000000099")


@dataclass(frozen=True, slots=True)
class EmptyState:
    scope_ids: ScopeIds = ScopeIds()


class CountingAuthorizer:
    def __init__(self) -> None:
        self.route_checks = 0
        self.scope_checks = 0

    def check(
        self, spec: CommandSpec, actor: ActorContext, input_value: BaseModel
    ) -> None:
        del spec, actor, input_value
        self.route_checks += 1

    def check_scope(
        self, spec: CommandSpec, actor: ActorContext, state: LoadedState
    ) -> None:
        del spec, actor, state
        self.scope_checks += 1

    def check_replayed_scope(
        self, spec: CommandSpec, actor: ActorContext, scope_ids: ScopeIds
    ) -> None:
        del spec, actor, scope_ids
        self.scope_checks += 1


async def empty_loader(
    _tx: AsyncSession, _input_value: BaseModel, *, lock: bool
) -> EmptyState:
    del lock
    await asyncio.sleep(0.05)
    return EmptyState()


async def notification_loader(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> EmptyState:
    assert isinstance(input_value, DeleteNotificationInput)
    statement = sa.text("SELECT id FROM notification_log WHERE id = :id")
    if lock:
        statement = sa.text(
            "SELECT id FROM notification_log WHERE id = :id FOR UPDATE"
        )
    notification_id = await tx.scalar(statement, {"id": input_value.id})
    if notification_id is None:
        raise RuntimeError("Notification no longer exists")
    return EmptyState()


def ping_decide(
    input_value: PingInput,
    _state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    return Plan(
        state_ops=[],
        events=[],
        deferred=[
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "ping",
                    "recipient": input_value.recipient,
                    "context": {"source": "executor-test"},
                },
                schedule_at=input_value.schedule_at,
            )
        ],
        audit={"subject_type": "harness", "details": {"ping": True}},
        summary={"accepted": True},
    )


def two_write_decide(
    _input_value: PingInput,
    _state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    common: dict[str, object] = {
        "event_key": "ping",
        "subject": "ping",
        "status": "sent",
        "attempts": 0,
        "context": {},
    }
    return Plan(
        state_ops=[
            StateOp(
                op="insert",
                model="notification_log",
                values={**common, "recipient": "one@example.edu"},
            ),
            StateOp(
                op="insert",
                model="notification_log",
                values={**common, "recipient": "two@example.edu"},
            ),
        ],
        events=[],
        deferred=[],
        audit=None,
        summary={"accepted": True},
    )


def delete_notification_decide(
    input_value: DeleteNotificationInput,
    _state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    return Plan(
        state_ops=[
            StateOp(
                op="delete",
                model="notification_log",
                values={},
                where={"id": input_value.id},
            )
        ],
        events=[],
        deferred=[],
        audit=None,
        summary={"deleted": True},
    )


def _registry() -> Registry:
    registry = Registry()
    registry.command(
        name="ping",
        input_model=PingInput,
        output_model=PingSummary,
        actor="test",
        scope="none",
        loader=empty_loader,
        rule_domains=(),
        spec_ids=("§16",),
    )(ping_decide)
    registry.command(
        name="two_write",
        input_model=PingInput,
        output_model=PingSummary,
        actor="test",
        scope="none",
        loader=empty_loader,
        rule_domains=(),
        spec_ids=("§16",),
    )(two_write_decide)
    registry.command(
        name="delete_notification",
        input_model=DeleteNotificationInput,
        output_model=DeleteNotificationSummary,
        actor="test",
        scope="none",
        loader=notification_loader,
        rule_domains=(),
        spec_ids=("§16",),
    )(delete_notification_decide)
    return registry


@pytest_asyncio.fixture(autouse=True)
async def clean_executor_tables() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, notification_log, "
                    "procrastinate_events, procrastinate_periodic_defers, "
                    "procrastinate_jobs RESTART IDENTITY CASCADE"
                )
            )
    finally:
        await engine.dispose()


def _executor(
    *, hooks: ExecutorHooks | None = None, authorizer: CountingAuthorizer | None = None
) -> tuple[Executor, object]:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    return (
        Executor(
            registry=_registry(),
            session_factory=factory,
            hooks=hooks,
            authorizer=authorizer,
        ),
        engine,
    )


async def _scalar(statement: str) -> object:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return await connection.scalar(sa.text(statement))
    finally:
        await engine.dispose()


async def _seed_notification() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO notification_log "
                    "(id, recipient, event_key, subject, status, attempts, context) "
                    "VALUES (:id, 'delete@example.edu', 'delete', 'delete', "
                    "'sent', 0, '{}'::jsonb)"
                ),
                {"id": DELETE_NOTIFICATION_ID},
            )
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_dry_run_explicitly_rolls_back_without_writes() -> None:
    executor, engine = _executor()
    try:
        preview = await executor.run(
            "ping", PingInput(), ActorContext(principal_id="student"), dry_run=True
        )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert preview.summary == {"accepted": True}
    assert await _scalar("SELECT count(*) FROM audit_log") == 0
    assert await _scalar("SELECT count(*) FROM procrastinate_jobs") == 0


@pytest.mark.asyncio
async def test_executor_checks_metadata_and_loaded_scope_authorization() -> None:
    authorizer = CountingAuthorizer()
    executor, engine = _executor(authorizer=authorizer)
    try:
        await executor.run("ping", PingInput(), ActorContext(principal_id="student"))
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert authorizer.route_checks == 1
    assert authorizer.scope_checks == 1


@pytest.mark.asyncio
async def test_g1_atomicity_rolls_back_mid_plan_failure() -> None:
    async def fail_after_first(index: int) -> None:
        if index == 1:
            raise RuntimeError("injected state-op failure")

    executor, engine = _executor(hooks=ExecutorHooks(after_state_op=fail_after_first))
    try:
        with pytest.raises(RuntimeError, match="injected state-op failure"):
            await executor.run(
                "two_write",
                PingInput(),
                ActorContext(principal_id="student"),
                idempotency_key="g1-failure",
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert await _scalar("SELECT count(*) FROM notification_log") == 0
    assert await _scalar("SELECT count(*) FROM audit_log") == 0
    assert await _scalar("SELECT count(*) FROM idempotency_keys") == 0
    assert await _scalar("SELECT count(*) FROM procrastinate_jobs") == 0


@pytest.mark.asyncio
async def test_g3_no_phantom_job_before_commit_failure() -> None:
    async def fail_before_commit() -> None:
        raise RuntimeError("injected pre-commit failure")

    executor, engine = _executor(hooks=ExecutorHooks(before_commit=fail_before_commit))
    try:
        with pytest.raises(RuntimeError, match="injected pre-commit failure"):
            await executor.run(
                "ping",
                PingInput(),
                ActorContext(principal_id="student"),
                idempotency_key="g3-failure",
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert await _scalar("SELECT count(*) FROM audit_log") == 0
    assert await _scalar("SELECT count(*) FROM idempotency_keys") == 0
    assert await _scalar("SELECT count(*) FROM procrastinate_jobs") == 0


@pytest.mark.asyncio
async def test_deferred_schedule_at_is_stored_on_the_job() -> None:
    schedule_at = datetime.now(UTC) + timedelta(days=1)
    executor, engine = _executor()
    try:
        await executor.run(
            "ping",
            PingInput(schedule_at=schedule_at),
            ActorContext(principal_id="student"),
        )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    stored = await _scalar("SELECT scheduled_at FROM procrastinate_jobs")
    assert stored == schedule_at


@pytest.mark.asyncio
async def test_idempotent_replay_returns_cached_result() -> None:
    authorizer = CountingAuthorizer()
    executor, engine = _executor(authorizer=authorizer)
    actor = ActorContext(principal_id="student")
    try:
        first = await executor.run("ping", PingInput(), actor, idempotency_key="ping-1")
        second = await executor.run("ping", PingInput(), actor, idempotency_key="ping-1")
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert first == second
    assert authorizer.route_checks == 2
    assert authorizer.scope_checks == 2
    assert await _scalar("SELECT count(*) FROM audit_log") == 1
    assert await _scalar("SELECT count(*) FROM procrastinate_jobs") == 1


@pytest.mark.asyncio
async def test_destructive_idempotent_replay_uses_cached_scope_without_reloading() -> None:
    await _seed_notification()
    authorizer = CountingAuthorizer()
    executor, engine = _executor(authorizer=authorizer)
    input_value = DeleteNotificationInput(id=DELETE_NOTIFICATION_ID)
    actor = ActorContext(principal_id="admin")
    try:
        first = await executor.run(
            "delete_notification",
            input_value,
            actor,
            idempotency_key="delete-notification",
        )
        second = await executor.run(
            "delete_notification",
            input_value,
            actor,
            idempotency_key="delete-notification",
        )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert first == second
    assert authorizer.route_checks == 2
    assert authorizer.scope_checks == 2
    assert await _scalar("SELECT count(*) FROM notification_log") == 0


@pytest.mark.asyncio
async def test_concurrent_idempotent_replay_has_one_effect_and_identical_results() -> None:
    executor, engine = _executor()
    actor = ActorContext(principal_id="student")
    try:
        first, second = await asyncio.gather(
            executor.run("ping", PingInput(), actor, idempotency_key="ping-race"),
            executor.run("ping", PingInput(), actor, idempotency_key="ping-race"),
        )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert first == second
    assert await _scalar("SELECT count(*) FROM audit_log") == 1
    assert await _scalar("SELECT count(*) FROM procrastinate_jobs") == 1


@pytest.mark.asyncio
async def test_idempotency_key_cannot_be_reused_by_another_command() -> None:
    executor, engine = _executor()
    actor = ActorContext(principal_id="student")
    try:
        await executor.run("ping", PingInput(), actor, idempotency_key="shared-key")
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "two_write", PingInput(), actor, idempotency_key="shared-key"
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert [reason.code for reason in error.value.rejection.reasons] == [
        IDEMPOTENCY_CONFLICT
    ]
    assert await _scalar("SELECT count(*) FROM notification_log") == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("second_input", "second_actor"),
    [
        (PingInput(), ActorContext(principal_id="another-student")),
        (
            PingInput(recipient="different@example.edu"),
            ActorContext(principal_id="student"),
        ),
    ],
)
async def test_idempotency_key_is_bound_to_principal_and_input(
    second_input: PingInput, second_actor: ActorContext
) -> None:
    executor, engine = _executor()
    try:
        await executor.run(
            "ping",
            PingInput(),
            ActorContext(principal_id="student"),
            idempotency_key="bound-key",
        )
        with pytest.raises(DomainRejection) as error:
            await executor.run(
                "ping",
                second_input,
                second_actor,
                idempotency_key="bound-key",
            )
    finally:
        await engine.dispose()  # type: ignore[union-attr]

    assert [reason.code for reason in error.value.rejection.reasons] == [
        IDEMPOTENCY_CONFLICT
    ]
    assert await _scalar("SELECT count(*) FROM audit_log") == 1
    assert await _scalar("SELECT count(*) FROM procrastinate_jobs") == 1
