"""M2 registry, generated-route, and route-limiter contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import get_args

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from app.bootstrap import build_registry
from app.core.errors import BulkInterrupted, DomainRejection, install_exception_handlers
from app.core.plan import ActorContext, Plan, Preview, Reason, Rejection, Result, ScopeIds
from app.core.rate_limit import InProcessRateLimiter
from app.core.registry import Registry
from app.core.routes import mount_registry_routes
from app.settings import Settings


class EchoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str


class EchoSummary(BaseModel):
    message: str


class BulkInput(BaseModel):
    rows: list[dict[str, int]]
    batch_key: str


class BulkSummary(BaseModel):
    count: int


class EmptyState:
    scope_ids = ScopeIds()


async def empty_loader(*_: object, **__: object) -> EmptyState:
    return EmptyState()


def echo_decide(input_value: EchoInput, *_: object) -> Plan | Rejection:
    if input_value.message == "reject":
        return Rejection(reasons=[Reason(code="not_eligible", human="Rejected by fixture")])
    return Plan(
        state_ops=[],
        events=[],
        deferred=[],
        audit=None,
        summary={"message": input_value.message},
    )


class FakeExecutor:
    def __init__(self) -> None:
        self.single_calls = 0
        self.bulk_calls = 0
        self.bulk_dry_runs: list[bool] = []

    async def run(
        self,
        name: str,
        input_value: BaseModel,
        actor: ActorContext,
        *,
        dry_run: bool = False,
        idempotency_key: str | None = None,
    ) -> Result:
        del name, actor, dry_run, idempotency_key
        self.single_calls += 1
        if isinstance(input_value, EchoInput) and input_value.message == "reject":
            raise DomainRejection(
                Rejection(reasons=[Reason(code="not_eligible", human="Rejected by fixture")])
            )
        echo_input = input_value if isinstance(input_value, EchoInput) else EchoInput(message="")
        return Result(summary={"message": echo_input.message}, events=[])

    async def run_bulk(
        self,
        name: str,
        rows: list[dict[str, object]],
        batch_key: str,
        actor: ActorContext,
        *,
        dry_run: bool = False,
        batch_fields: Mapping[str, object] | None = None,
    ) -> Preview | Result:
        del name, batch_key, actor, batch_fields
        self.bulk_calls += 1
        self.bulk_dry_runs.append(dry_run)
        result_type = Preview if dry_run else Result
        return result_type(summary={"count": len(rows)}, events=[])


class InterruptExecutor(FakeExecutor):
    def __init__(self, reasons: list[Reason] | None = None) -> None:
        super().__init__()
        self.reasons = reasons

    async def run_bulk(
        self,
        name: str,
        rows: list[dict[str, object]],
        batch_key: str,
        actor: ActorContext,
        *,
        dry_run: bool = False,
        batch_fields: Mapping[str, object] | None = None,
    ) -> Preview | Result:
        del name, rows, actor, dry_run, batch_fields
        raise BulkInterrupted(
            batch_key=batch_key,
            completed_chunks=[1, 2],
            failed_chunk=3,
            reasons=self.reasons,
        )


async def harness_actor() -> ActorContext:
    return ActorContext(principal_id="harness")


def _registry() -> Registry:
    registry = Registry()
    registry.command(
        name="echo",
        input_model=EchoInput,
        output_model=EchoSummary,
        actor="test",
        scope="none",
        loader=empty_loader,
        rule_domains=(),
        spec_ids=("§16",),
    )(echo_decide)
    registry.command(
        name="bulk_echo",
        input_model=BulkInput,
        output_model=BulkSummary,
        actor="test",
        scope="none",
        loader=empty_loader,
        rule_domains=(),
        spec_ids=("§16",),
        rate_limit="1/min",
        execution_mode="bulk",
    )(echo_decide)
    return registry


def test_registry_rejects_duplicate_names() -> None:
    registry = _registry()

    with pytest.raises(ValueError, match="echo"):
        registry.command(
            name="echo",
            input_model=EchoInput,
            output_model=EchoSummary,
            actor="test",
            scope="none",
            loader=empty_loader,
            rule_domains=(),
            spec_ids=("§16",),
        )(echo_decide)

    @registry.screen(id="echo-screen", roles=("test",))
    async def echo_screen() -> EchoSummary:
        return EchoSummary(message="ok")

    with pytest.raises(ValueError, match="echo-screen"):
        registry.screen(id="echo-screen", roles=("test",))(echo_screen)


@pytest.mark.asyncio
async def test_generated_route_is_typed_and_rejections_are_problem_json() -> None:
    app = FastAPI()
    executor = FakeExecutor()
    install_exception_handlers(app)
    mount_registry_routes(
        app,
        registry=_registry(),
        executor=executor,
        actor_provider=harness_actor,
        limiter=InProcessRateLimiter(),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/commands/echo",
            json={"input": {"message": "hello"}, "dry_run": False},
        )
        rejection = await client.post(
            "/api/v1/commands/echo",
            json={"input": {"message": "reject"}, "dry_run": False},
        )

    assert response.status_code == 200
    assert response.json() == {"summary": {"message": "hello"}}
    assert rejection.status_code == 409
    assert rejection.headers["content-type"].startswith("application/problem+json")
    assert rejection.json()["reasons"] == [
        {"code": "not_eligible", "human": "Rejected by fixture", "path": None}
    ]

    request_schema = app.openapi()["components"]["schemas"]["EchoCommandRequest"]
    assert request_schema["properties"]["input"]["$ref"].endswith("/EchoInput")


@pytest.mark.asyncio
async def test_generated_route_validation_is_problem_json() -> None:
    app = FastAPI()
    install_exception_handlers(app)
    mount_registry_routes(
        app,
        registry=_registry(),
        executor=FakeExecutor(),
        actor_provider=harness_actor,
        limiter=InProcessRateLimiter(),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/commands/echo",
            json={"input": {}},
        )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json() == {
        "type": "/problems/request-validation",
        "title": "Invalid request",
        "status": 422,
        "reasons": [
            {
                "code": "invalid_request",
                "human": "Field required",
                "path": "input.message",
            }
        ],
    }


@pytest.mark.asyncio
async def test_bulk_rate_limit_is_one_unit_at_the_route_layer() -> None:
    app = FastAPI()
    executor = FakeExecutor()
    install_exception_handlers(app)
    mount_registry_routes(
        app,
        registry=_registry(),
        executor=executor,
        actor_provider=harness_actor,
        limiter=InProcessRateLimiter(),
    )
    payload = {
        "input": {"rows": [{"row": index} for index in range(1200)], "batch_key": "batch-a"},
        "dry_run": False,
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/v1/commands/bulk_echo", json=payload)
        second = await client.post("/api/v1/commands/bulk_echo", json=payload)

    assert first.status_code == 200
    assert first.json() == {"summary": {"count": 1200}}
    assert second.status_code == 429
    assert executor.bulk_calls == 1


@pytest.mark.asyncio
async def test_bulk_route_forwards_dry_run_without_executing_chunks() -> None:
    app = FastAPI()
    executor = FakeExecutor()
    install_exception_handlers(app)
    mount_registry_routes(
        app,
        registry=_registry(),
        executor=executor,
        actor_provider=harness_actor,
        limiter=InProcessRateLimiter(),
    )
    payload = {
        "input": {"rows": [{"row": index} for index in range(1200)], "batch_key": "preview"},
        "dry_run": True,
    }

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/v1/commands/bulk_echo", json=payload)

    assert response.status_code == 200
    assert response.json() == {"summary": {"count": 1200}, "events": []}
    assert executor.bulk_dry_runs == [True]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reasons", "expected_status"),
    [
        (None, 500),
        ([Reason(code="invalid_transition", human="Chunk rejected")], 409),
    ],
)
async def test_bulk_interruption_response_contains_resume_coordinates(
    reasons: list[Reason] | None, expected_status: int
) -> None:
    app = FastAPI()
    install_exception_handlers(app)
    mount_registry_routes(
        app,
        registry=_registry(),
        executor=InterruptExecutor(reasons),
        actor_provider=harness_actor,
        limiter=InProcessRateLimiter(),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/commands/bulk_echo",
            json={
                "input": {"rows": [{"row": 1}], "batch_key": "resume-me"},
                "dry_run": False,
            },
        )

    assert response.status_code == expected_status
    expected: dict[str, object] = {
        "type": "/problems/bulk-interrupted",
        "title": "Bulk execution interrupted",
        "status": expected_status,
        "batch_key": "resume-me",
        "completed_chunks": [1, 2],
        "failed_chunk": 3,
        "detail": "Replay with the same batch key to resume",
    }
    if reasons:
        expected["reasons"] = [
            {"code": "invalid_transition", "human": "Chunk rejected", "path": None}
        ]
    assert response.json() == expected


def _nested_models(model: type[BaseModel]) -> set[type[BaseModel]]:
    found: set[type[BaseModel]] = set()
    pending = [model]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        for field in current.model_fields.values():
            for argument in (field.annotation, *get_args(field.annotation)):
                if isinstance(argument, type) and issubclass(argument, BaseModel):
                    pending.append(argument)
                for nested in get_args(argument):
                    if isinstance(nested, type) and issubclass(nested, BaseModel):
                        pending.append(nested)
    return found


def test_every_command_input_model_forbids_extra_fields() -> None:
    """A silently dropped field is indistinguishable from an honoured one."""
    registry = build_registry(
        settings=Settings(session_secret="routes-test-session-secret-32-chars", dev_login=True),
        enable_test_harness=True,
    )
    permissive = sorted(
        f"{model.__module__}.{model.__qualname__}"
        for spec in registry.commands.values()
        for model in _nested_models(spec.input_model)
        if model.model_config.get("extra") != "forbid"
    )
    assert permissive == []


@pytest.mark.asyncio
async def test_unknown_request_fields_are_rejected_not_dropped() -> None:
    app = FastAPI()
    install_exception_handlers(app)
    mount_registry_routes(
        app,
        registry=_registry(),
        executor=FakeExecutor(),
        actor_provider=harness_actor,
        limiter=InProcessRateLimiter(),
    )

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        unknown_input_field = await client.post(
            "/api/v1/commands/echo",
            json={"input": {"message": "hello", "escalate": True}},
        )
        unknown_envelope_field = await client.post(
            "/api/v1/commands/echo",
            json={"input": {"message": "hello"}, "dryrun": True},
        )

    assert unknown_input_field.status_code == 422
    assert [reason["path"] for reason in unknown_input_field.json()["reasons"]] == [
        "input.escalate"
    ]
    assert unknown_envelope_field.status_code == 422
    assert [reason["path"] for reason in unknown_envelope_field.json()["reasons"]] == [
        "dryrun"
    ]
