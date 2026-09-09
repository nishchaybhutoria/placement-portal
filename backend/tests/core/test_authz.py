"""Registry authorization contracts for Behavior IDN-3."""

from __future__ import annotations

import os
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.authz import Authorizer
from app.core.db import create_engine
from app.core.errors import (
    AuthorizationDenied,
    DomainRejection,
    install_exception_handlers,
)
from app.core.executor import Executor
from app.core.plan import ActorContext, Plan, Rejection, ScopeIds
from app.core.rate_limit import InProcessRateLimiter
from app.core.registry import ActorPolicy, Registry, ScopePolicy
from app.core.routes import mount_registry_routes

CYCLE_A = UUID("00000000-0000-0000-0000-0000000000a1")
CYCLE_B = UUID("00000000-0000-0000-0000-0000000000b1")
ENROLLMENT = UUID("00000000-0000-0000-0000-0000000000e1")
USER = UUID("00000000-0000-0000-0000-0000000000f1")
SESSION = UUID("00000000-0000-0000-0000-0000000000f2")


class ProbeInput(BaseModel):
    cycle_id: UUID | None = None


class ProbeSummary(BaseModel):
    allowed: bool


@dataclass(frozen=True, slots=True)
class ProbeState:
    scope_ids: ScopeIds
    cycle_archived: bool = False


async def _probe_loader(
    _tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ProbeState:
    del lock
    assert isinstance(input_value, ProbeInput)
    return ProbeState(scope_ids=ScopeIds(cycle_id=input_value.cycle_id))


def _probe_decide(
    _input: BaseModel,
    _state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    return Plan(
        state_ops=[],
        events=[],
        deferred=[],
        audit=None,
        summary={"allowed": True},
    )


def _registry(*, actor: ActorPolicy, scope: ScopePolicy) -> Registry:
    registry = Registry()
    registry.command(
        name="probe",
        input_model=ProbeInput,
        output_model=ProbeSummary,
        actor=actor,
        scope=scope,
        loader=_probe_loader,
        rule_domains=(),
        spec_ids=("IDN-3",),
    )(_probe_decide)
    return registry


def _anonymous() -> ActorContext:
    return ActorContext(principal_id="anonymous")


def _student(*, enrollment: bool = True, cycles: tuple[UUID, ...] = ()) -> ActorContext:
    return ActorContext(
        principal_id=str(USER),
        user_id=USER,
        role="student",
        session_id=SESSION,
        current_enrollment_id=ENROLLMENT if enrollment else None,
        coordinated_cycle_ids=cycles,
    )


def _admin() -> ActorContext:
    return ActorContext(
        principal_id=str(USER),
        user_id=USER,
        role="admin",
        session_id=SESSION,
    )


@pytest.mark.parametrize(
    ("policy", "actor", "allowed"),
    [
        ("anonymous", _anonymous(), True),
        ("anonymous", _student(), True),
        ("authenticated", _anonymous(), False),
        ("authenticated", _student(), True),
        ("student", _student(enrollment=False), False),
        ("student", _student(), True),
        ("student", _admin(), False),
        ("admin", _student(), False),
        ("admin", _admin(), True),
        ("system", ActorContext(principal_id="system", is_system=True), True),
        ("system", _admin(), False),
        (
            "test",
            ActorContext(principal_id="harness", is_test_harness=True),
            True,
        ),
        ("test", _admin(), False),
    ],
)
def test_IDN3_typed_actor_policies_fail_closed(
    policy: ActorPolicy, actor: ActorContext, allowed: bool
) -> None:
    spec = _registry(actor=policy, scope="none").commands["probe"]

    if allowed:
        Authorizer().check(spec, actor, ProbeInput())
    else:
        with pytest.raises(AuthorizationDenied):
            Authorizer().check(spec, actor, ProbeInput())


@pytest.mark.parametrize(
    ("actor", "cycle_id", "allowed"),
    [
        (_anonymous(), CYCLE_A, False),
        (_student(), CYCLE_A, False),
        (_student(cycles=(CYCLE_A,)), CYCLE_A, True),
        (_student(cycles=(CYCLE_A,)), CYCLE_B, False),
        (_admin(), CYCLE_B, True),
    ],
)
def test_IDN3_staff_cycle_is_admin_or_matching_coordinator(
    actor: ActorContext, cycle_id: UUID, allowed: bool
) -> None:
    spec = _registry(actor="staff", scope="cycle").commands["probe"]
    input_value = ProbeInput(cycle_id=cycle_id)
    state = ProbeState(scope_ids=ScopeIds(cycle_id=cycle_id))

    if allowed:
        Authorizer().check(spec, actor, input_value)
        Authorizer().check_scope(spec, actor, state)
    else:
        with pytest.raises(AuthorizationDenied):
            Authorizer().check(spec, actor, input_value)


@pytest.mark.asyncio
async def test_IDN3_wrong_cycle_coordinator_receives_rfc7807_403() -> None:
    registry = _registry(actor="staff", scope="cycle")
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    executor = Executor(
        registry=registry,
        session_factory=async_sessionmaker[AsyncSession](
            engine, expire_on_commit=False, autobegin=False
        ),
        authorizer=Authorizer(),
    )
    application = FastAPI()
    install_exception_handlers(application)

    async def coordinator() -> ActorContext:
        return _student(cycles=(CYCLE_A,))

    mount_registry_routes(
        application,
        registry=registry,
        executor=executor,
        actor_provider=coordinator,
        limiter=InProcessRateLimiter(),
    )
    try:
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/v1/commands/probe",
                json={"input": {"cycle_id": str(CYCLE_B)}},
            )
    finally:
        await engine.dispose()

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "/problems/forbidden",
        "title": "Forbidden",
        "status": 403,
    }


@pytest_asyncio.fixture(autouse=True)
async def clean_idempotency() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(sa.text("TRUNCATE idempotency_keys CASCADE"))
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_IDN3_cached_idempotency_replay_rechecks_loaded_cycle_scope() -> None:
    registry = _registry(actor="staff", scope="cycle")
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    executor = Executor(
        registry=registry,
        session_factory=async_sessionmaker[AsyncSession](
            engine, expire_on_commit=False, autobegin=False
        ),
        authorizer=Authorizer(),
    )
    scoped_actor = _student(cycles=(CYCLE_A,))
    same_principal_wrong_scope = _student(cycles=(CYCLE_B,))
    input_value = ProbeInput(cycle_id=CYCLE_A)
    try:
        await executor.run(
            "probe", input_value, scoped_actor, idempotency_key="scope-replay"
        )
        with pytest.raises(AuthorizationDenied):
            await executor.run(
                "probe",
                input_value,
                same_principal_wrong_scope,
                idempotency_key="scope-replay",
            )
    finally:
        await engine.dispose()


def test_IDN3_a_cached_replay_is_exempt_from_the_archival_check() -> None:
    """A replay reads back a committed result; it writes nothing (CYC-1)."""
    registry = Registry()
    registry.command(
        name="archived_probe",
        input_model=ProbeInput,
        output_model=ProbeSummary,
        actor="staff",
        scope="cycle",
        loader=_probe_loader,
        rule_domains=(),
        spec_ids=("CYC-1",),
    )(_probe_decide)
    spec = registry.commands["archived_probe"]
    cycle_id = uuid4()
    actor = ActorContext(
        principal_id="admin", user_id=uuid4(), role="admin", session_id=uuid4()
    )

    # Loading an archived cycle rejects, but replaying its recorded result does not.
    with pytest.raises(DomainRejection):
        Authorizer().check_scope(
            spec,
            actor,
            ProbeState(scope_ids=ScopeIds(cycle_id=cycle_id), cycle_archived=True),
        )
    Authorizer().check_replayed_scope(spec, actor, ScopeIds(cycle_id=cycle_id))


def test_IDN3_a_cached_replay_still_enforces_cycle_scope() -> None:
    registry = Registry()
    registry.command(
        name="scoped_probe",
        input_model=ProbeInput,
        output_model=ProbeSummary,
        actor="staff",
        scope="cycle",
        loader=_probe_loader,
        rule_domains=(),
        spec_ids=("IDN-3",),
    )(_probe_decide)
    spec = registry.commands["scoped_probe"]
    mine, theirs = uuid4(), uuid4()
    coordinator = ActorContext(
        principal_id="coord",
        user_id=uuid4(),
        role="student",
        session_id=uuid4(),
        coordinated_cycle_ids=(mine,),
    )

    Authorizer().check_replayed_scope(spec, coordinator, ScopeIds(cycle_id=mine))
    with pytest.raises(AuthorizationDenied):
        Authorizer().check_replayed_scope(spec, coordinator, ScopeIds(cycle_id=theirs))


def test_IDN3_a_cycle_scoped_state_without_the_archival_flag_fails_closed() -> None:
    """The guard the replay exemption must not weaken."""

    @dataclass(frozen=True, slots=True)
    class ForgetfulState:
        scope_ids: ScopeIds

    registry = Registry()
    registry.command(
        name="forgetful_probe",
        input_model=ProbeInput,
        output_model=ProbeSummary,
        actor="admin",
        scope="cycle",
        loader=_probe_loader,
        rule_domains=(),
        spec_ids=("CYC-1",),
    )(_probe_decide)
    actor = ActorContext(
        principal_id="admin", user_id=uuid4(), role="admin", session_id=uuid4()
    )

    with pytest.raises(RuntimeError, match="without cycle_archived"):
        Authorizer().check_scope(
            registry.commands["forgetful_probe"],
            actor,
            ForgetfulState(scope_ids=ScopeIds(cycle_id=uuid4())),
        )
