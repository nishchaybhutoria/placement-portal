"""M2 resumable bulk contract from LLD section 5."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import cast
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bootstrap import build_registry
from app.core.authz import Authorizer
from app.core.db import create_engine
from app.core.errors import (
    IDEMPOTENCY_CONFLICT,
    AuthorizationDenied,
    BulkInterrupted,
    DomainRejection,
)
from app.core.executor import Executor
from app.core.plan import ActorContext, Plan, Reason, Rejection, ScopeIds, StateOp
from app.core.registry import Registry


class BulkRowsInput(BaseModel):
    rows: list[dict[str, int]]
    batch_key: str


class BulkRowsSummary(BaseModel):
    rows: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class EmptyState:
    scope_ids: ScopeIds = ScopeIds()


async def empty_loader(
    _tx: AsyncSession, _input_value: BaseModel, *, lock: bool
) -> EmptyState:
    del lock
    return EmptyState()


class FailThirdChunkOnce:
    def __init__(self) -> None:
        self.failed = False

    def __call__(
        self,
        input_value: BulkRowsInput,
        _state: object,
        _policy: object,
        _overrides: object,
        _actor: ActorContext,
    ) -> Plan | Rejection:
        if input_value.rows[0]["row"] == 1000 and not self.failed:
            self.failed = True
            raise DomainRejection(
                Rejection(
                    reasons=[
                        Reason(code="invalid_transition", human="Injected chunk failure")
                    ]
                )
            )

        operations = [
            StateOp(
                op="insert",
                model="notification_log",
                values={
                    "recipient": f"row-{row['row']}@example.edu",
                    "event_key": "bulk",
                    "subject": "bulk",
                    "status": "sent",
                    "attempts": 0,
                    "context": {"row": row["row"]},
                },
            )
            for row in input_value.rows
        ]
        return Plan(
            state_ops=operations,
            events=[],
            deferred=[],
            audit={"subject_type": "bulk_chunk", "details": {}},
            summary={
                "rows": [
                    {"row": row["row"], "status": "applied"} for row in input_value.rows
                ]
            },
        )


class MalformedBulkDecider:
    def __call__(
        self,
        input_value: BulkRowsInput,
        _state: object,
        _policy: object,
        _overrides: object,
        _actor: ActorContext,
    ) -> Plan | Rejection:
        return Plan(
            state_ops=[
                StateOp(
                    op="insert",
                    model="notification_log",
                    values={
                        "recipient": "malformed@example.edu",
                        "event_key": "bulk",
                        "subject": "bulk",
                        "status": "sent",
                        "attempts": 0,
                        "context": {"row": input_value.rows[0]["row"]},
                    },
                )
            ],
            events=[],
            deferred=[],
            audit={"subject_type": "bulk_chunk", "details": {}},
            summary={"unexpected": []},
        )


@pytest_asyncio.fixture(autouse=True)
async def clean_bulk_tables() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text("TRUNCATE audit_log, idempotency_keys, notification_log CASCADE")
            )
    finally:
        await engine.dispose()


async def _scalar(statement: str) -> object:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            return await connection.scalar(sa.text(statement))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_chunking_reports_progress_and_replays_only_missing_chunk() -> None:
    decider = FailThirdChunkOnce()
    registry = Registry()
    registry.command(
        name="bulk_rows",
        input_model=BulkRowsInput,
        output_model=BulkRowsSummary,
        actor="test",
        scope="none",
        loader=empty_loader,
        rule_domains=(),
        spec_ids=("§16",),
        execution_mode="bulk",
    )(decider)
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    executor = Executor(registry=registry, session_factory=factory)
    rows: list[dict[str, object]] = [{"row": index} for index in range(1200)]

    try:
        with pytest.raises(BulkInterrupted) as error:
            await executor.run_bulk(
                "bulk_rows", rows, "batch-1200", ActorContext(principal_id="admin")
            )
        assert error.value.batch_key == "batch-1200"
        assert error.value.completed_chunks == [1, 2]
        assert error.value.failed_chunk == 3
        assert [reason.code for reason in error.value.reasons] == ["invalid_transition"]
        assert await _scalar("SELECT count(*) FROM audit_log") == 1

        changed_rows = [dict(row) for row in rows]
        changed_rows[-1] = {"row": 9999}
        with pytest.raises(DomainRejection) as mismatch:
            await executor.run_bulk(
                "bulk_rows",
                changed_rows,
                "batch-1200",
                ActorContext(principal_id="admin"),
            )
        assert [reason.code for reason in mismatch.value.rejection.reasons] == [
            IDEMPOTENCY_CONFLICT
        ]

        replay = await executor.run_bulk(
            "bulk_rows", rows, "batch-1200", ActorContext(principal_id="admin")
        )
    finally:
        await engine.dispose()

    assert len(cast(list[object], replay.summary["rows"])) == 1200
    migration_engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with migration_engine.connect() as connection:
            assert await connection.scalar(sa.text("SELECT count(*) FROM notification_log")) == 1200
            assert await connection.scalar(sa.text("SELECT count(*) FROM audit_log")) == 1
            keys = (
                await connection.scalars(
                    sa.text("SELECT key FROM idempotency_keys ORDER BY key")
                )
            ).all()
    finally:
        await migration_engine.dispose()
    assert keys == [
        "batch-1200:1",
        "batch-1200:2",
        "batch-1200:3",
    ]


@pytest.mark.asyncio
async def test_malformed_bulk_summary_rolls_back_the_chunk() -> None:
    registry = Registry()
    registry.command(
        name="malformed_bulk",
        input_model=BulkRowsInput,
        output_model=BulkRowsSummary,
        actor="test",
        scope="none",
        loader=empty_loader,
        rule_domains=(),
        spec_ids=("§16",),
        execution_mode="bulk",
    )(MalformedBulkDecider())
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    executor = Executor(registry=registry, session_factory=factory)

    try:
        with pytest.raises(BulkInterrupted):
            await executor.run_bulk(
                "malformed_bulk",
                [{"row": 1}],
                "malformed-batch",
                ActorContext(principal_id="admin"),
            )
    finally:
        await engine.dispose()

    assert await _scalar("SELECT count(*) FROM notification_log") == 0
    assert await _scalar("SELECT count(*) FROM audit_log") == 0
    assert await _scalar("SELECT count(*) FROM idempotency_keys") == 0


class ScopedBulkInput(BaseModel):
    cycle_id: UUID
    rows: list[dict[str, int]]
    batch_key: str


@dataclass(frozen=True, slots=True)
class ScopedState:
    scope_ids: ScopeIds
    cycle_archived: bool = False


async def scoped_loader(
    _tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ScopedState:
    del lock
    scoped = cast(ScopedBulkInput, input_value)
    return ScopedState(scope_ids=ScopeIds(cycle_id=scoped.cycle_id))


def scoped_decider(
    input_value: ScopedBulkInput,
    _state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Record which scope each chunk was decided under."""
    return Plan(
        state_ops=[],
        events=[],
        deferred=[],
        audit=None,
        summary={
            "rows": [
                {"row": row["row"], "cycle_id": str(input_value.cycle_id)}
                for row in input_value.rows
            ]
        },
    )


def _scoped_registry() -> Registry:
    registry = Registry()
    registry.command(
        name="scoped_bulk",
        input_model=ScopedBulkInput,
        output_model=BulkRowsSummary,
        actor="staff",
        scope="cycle",
        loader=scoped_loader,
        rule_domains=(),
        spec_ids=("§16",),
        execution_mode="bulk",
    )(scoped_decider)
    return registry


@pytest.mark.asyncio
async def test_bulk_batch_fields_reach_every_chunk() -> None:
    registry = _scoped_registry()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    executor = Executor(registry=registry, session_factory=factory)
    cycle_id = uuid4()
    rows: list[dict[str, object]] = [{"row": index} for index in range(600)]

    try:
        result = await executor.run_bulk(
            "scoped_bulk",
            rows,
            "scoped-batch",
            ActorContext(principal_id="admin"),
            batch_fields={"cycle_id": cycle_id},
        )
    finally:
        await engine.dispose()

    reported = cast(list[dict[str, object]], result.summary["rows"])
    assert len(reported) == 600
    # Both chunks, not just the first, decided under the batch's scope.
    assert {row["cycle_id"] for row in reported} == {str(cycle_id)}


@pytest.mark.asyncio
async def test_bulk_batch_fields_may_not_restate_the_row_payload() -> None:
    registry = _scoped_registry()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    executor = Executor(registry=registry, session_factory=factory)
    try:
        with pytest.raises(ValueError, match="restate rows or batch_key"):
            await executor.run_bulk(
                "scoped_bulk",
                [{"row": 1}],
                "restated",
                ActorContext(principal_id="admin"),
                batch_fields={"cycle_id": uuid4(), "rows": []},
            )
    finally:
        await engine.dispose()


def test_IDN3_scoped_bulk_command_checks_batch_scope_at_the_route_stage() -> None:
    """The stage-one authorizer sees a bulk command's scope (CONTRIBUTING.md invariant 8)."""
    registry = _scoped_registry()
    spec = registry.commands["scoped_bulk"]
    cycle_a, cycle_b, user, session = uuid4(), uuid4(), uuid4(), uuid4()
    input_value = spec.input_model.model_validate(
        {"cycle_id": cycle_a, "rows": [{"row": 1}], "batch_key": "scoped"}
    )

    def coordinator(cycle_id: UUID) -> ActorContext:
        return ActorContext(
            principal_id=str(user),
            user_id=user,
            role="student",
            session_id=session,
            coordinated_cycle_ids=(cycle_id,),
        )

    Authorizer().check(spec, coordinator(cycle_a), input_value)
    with pytest.raises(AuthorizationDenied):
        Authorizer().check(spec, coordinator(cycle_b), input_value)


@pytest.mark.asyncio
async def test_bulk_fingerprint_separates_identical_rows_under_different_scopes() -> None:
    """Without the scope in the fingerprint, cycle B would replay cycle A's result."""
    registry = _scoped_registry()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    executor = Executor(registry=registry, session_factory=factory)
    actor = ActorContext(principal_id="admin")
    rows: list[dict[str, object]] = [{"row": 1}]
    cycle_a, cycle_b = uuid4(), uuid4()

    try:
        first = await executor.run_bulk(
            "scoped_bulk", rows, "shared-key", actor, batch_fields={"cycle_id": cycle_a}
        )
        with pytest.raises(DomainRejection) as conflict:
            await executor.run_bulk(
                "scoped_bulk",
                rows,
                "shared-key",
                actor,
                batch_fields={"cycle_id": cycle_b},
            )
    finally:
        await engine.dispose()

    assert cast(list[dict[str, object]], first.summary["rows"])[0]["cycle_id"] == str(
        cycle_a
    )
    assert [reason.code for reason in conflict.value.rejection.reasons] == [
        IDEMPOTENCY_CONFLICT
    ]


@pytest.mark.asyncio
async def test_a_denied_bulk_command_is_a_denial_not_an_interrupted_batch() -> None:
    """A denial is not a partial failure (the design review section 4.23).

    ``BulkInterrupted`` says "some of your rows did not apply" and carries the
    coordinates to resume from.  Applied to an authorization denial, both
    halves are false: nothing applied, and every resume attempt is denied
    again.  It also reaches the client as a 500 where the truth is a 403.
    """
    registry = _scoped_registry()
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    executor = Executor(
        registry=registry, session_factory=factory, authorizer=Authorizer()
    )
    user, session = uuid4(), uuid4()
    outsider = ActorContext(
        principal_id=str(user),
        user_id=user,
        role="student",
        session_id=session,
        coordinated_cycle_ids=(uuid4(),),
    )

    try:
        with pytest.raises(AuthorizationDenied) as denial:
            await executor.run_bulk(
                "scoped_bulk",
                [{"row": 1}],
                "denied-batch",
                outsider,
                batch_fields={"cycle_id": uuid4()},
            )
    finally:
        await engine.dispose()

    assert denial.value.status == 403


def test_a_bulk_command_promises_only_what_run_bulk_can_return() -> None:
    """Chunk aggregation keeps ``rows`` and drops everything else.

    ``run_bulk`` combines chunks into ``{"rows": [...]}``: a batch-level count
    computed inside one chunk's decide has no meaning across three of them, so
    it is deliberately not carried.  An output model that *requires* such a
    field therefore describes a response the command can never produce, and
    FastAPI turns the mismatch into a 500 on a command that worked -- which is
    how four M10b round operations shipped unable to answer over HTTP at all.

    The row list is the contract; this keeps every future bulk command honest
    about that, at the cost of one assertion nobody has to remember to write.
    """
    registry = build_registry()
    offenders = {
        name: sorted(
            field
            for field, info in spec.output_model.model_fields.items()
            if info.is_required() and field != "rows"
        )
        for name, spec in registry.commands.items()
        if spec.execution_mode == "bulk"
    }
    assert {name: fields for name, fields in offenders.items() if fields} == {}
    assert offenders, "no bulk commands found -- the check would pass vacuously"
