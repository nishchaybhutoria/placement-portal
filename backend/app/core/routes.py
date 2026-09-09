"""FastAPI routes generated from command and screen registries."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from typing import Protocol, cast, get_type_hints

from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel, ConfigDict, create_model

from app.core.plan import ActorContext, Preview, Result
from app.core.rate_limit import InProcessRateLimiter
from app.core.registry import CommandSpec, Registry, ScreenSpec


class CommandExecutor(Protocol):
    async def run(
        self,
        name: str,
        input_value: BaseModel,
        actor: ActorContext,
        *,
        dry_run: bool = False,
        idempotency_key: str | None = None,
    ) -> Preview | Result: ...

    async def run_bulk(
        self,
        name: str,
        rows: list[dict[str, object]],
        batch_key: str,
        actor: ActorContext,
        *,
        dry_run: bool = False,
        batch_fields: Mapping[str, object] | None = None,
    ) -> Preview | Result: ...


ActorProvider = Callable[..., Awaitable[ActorContext]]


class SessionEffects(Protocol):
    def prepare_input(
        self, spec: CommandSpec, input_value: BaseModel, actor: ActorContext
    ) -> BaseModel: ...

    def apply_effect(
        self, response: Response, spec: CommandSpec, input_value: BaseModel
    ) -> None: ...


class RouteAuthorizer(Protocol):
    def check(
        self, spec: CommandSpec, actor: ActorContext, input_value: BaseModel
    ) -> None: ...

    def check_screen(self, spec: ScreenSpec, actor: ActorContext) -> None: ...


class CommandBody(Protocol):
    input: BaseModel
    dry_run: bool
    idempotency_key: str | None


class BulkCommandInput(Protocol):
    rows: list[dict[str, object]]
    batch_key: str


def _model_prefix(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("_"))


def _command_endpoint(
    spec: CommandSpec,
    executor: CommandExecutor,
    actor_provider: ActorProvider,
    limiter: InProcessRateLimiter,
    session_effects: SessionEffects | None,
    route_authorizer: RouteAuthorizer | None,
) -> tuple[Callable[..., Awaitable[dict[str, object]]], type[BaseModel], object]:
    prefix = _model_prefix(spec.name)
    request_model = create_model(
        f"{prefix}CommandRequest",
        # Unknown keys are refused here for the same reason every command input
        # refuses them: a field the server silently drops is indistinguishable,
        # from the caller's side, from a field the server honoured.
        __config__=ConfigDict(extra="forbid"),
        input=(spec.input_model, ...),
        dry_run=(bool, False),
        idempotency_key=(str | None, None),
    )
    execute_model = create_model(f"{prefix}CommandResult", summary=(spec.output_model, ...))
    preview_model = create_model(
        f"{prefix}CommandPreview",
        summary=(spec.output_model, ...),
        events=(list[dict[str, object]], ...),
    )
    actor_dependency = Depends(actor_provider)

    async def endpoint(
        body: BaseModel,
        response: Response,
        actor: ActorContext = actor_dependency,
    ) -> dict[str, object]:
        command_body = cast(CommandBody, body)
        dry_run = command_body.dry_run
        # the design review §4.39: the budget is a *write* budget. A dry run commits
        # nothing, and `PreviewConfirm` re-previews whenever the operator edits
        # a choice, so charging previews against it made the allowance on a
        # `10/min` command roughly three confirmations a minute -- and let
        # typing a reason exhaust the allowance for the action being previewed.
        # Authorization is unaffected: both checks below still run on a preview.
        if not dry_run:
            await limiter.check(actor.principal_id, spec.name, spec.rate_limit)
        input_value = command_body.input
        if session_effects is not None:
            input_value = session_effects.prepare_input(spec, input_value, actor)
        if route_authorizer is not None:
            route_authorizer.check(spec, actor, input_value)
        idempotency_key = command_body.idempotency_key
        if spec.execution_mode == "bulk":
            bulk_input = cast(BulkCommandInput, input_value)
            result = await executor.run_bulk(
                spec.name,
                bulk_input.rows,
                bulk_input.batch_key,
                actor,
                dry_run=dry_run,
                # A scoped bulk command (cycle_id, later job_id) states its scope
                # once for the batch; every chunk re-validates it with the rows.
                batch_fields=input_value.model_dump(exclude={"rows", "batch_key"}),
            )
        else:
            result = await executor.run(
                spec.name,
                input_value,
                actor,
                dry_run=dry_run,
                idempotency_key=idempotency_key,
            )
        payload: dict[str, object] = {"summary": result.summary}
        if isinstance(result, Preview):
            payload["events"] = [
                {
                    "application_id": str(event.application_id)
                    if event.application_id is not None
                    else None,
                    "event_type": event.event_type.value,
                    "from_status": event.from_status,
                    "to_status": event.to_status,
                    "from_round": str(event.from_round) if event.from_round else None,
                    "to_round": str(event.to_round) if event.to_round else None,
                    "reason": event.reason,
                    "payload": event.payload,
                }
                for event in result.events
            ]
        elif session_effects is not None and spec.session_effect is not None:
            session_effects.apply_effect(response, spec, input_value)
        return payload

    endpoint.__name__ = f"command_{spec.name}"
    endpoint.__annotations__["body"] = request_model
    return endpoint, request_model, execute_model | preview_model


def _screen_endpoint(spec: ScreenSpec, actor_provider: ActorProvider) -> Callable[..., object]:
    """Bind the request actor into screen handlers that ask for one.

    Screens are registered as endpoints directly, so a handler that needs the
    caller (student screens do) has no other way to receive it; commands get the
    same actor from the same provider.
    """
    handler = spec.handler
    signature = inspect.signature(handler)
    hints = get_type_hints(handler)
    parameters = [
        parameter.replace(annotation=hints.get(parameter.name, parameter.annotation))
        for parameter in signature.parameters.values()
    ]
    actor_names = [
        parameter.name
        for parameter in parameters
        if parameter.annotation is ActorContext
    ]
    if not actor_names:
        return handler
    bound = [
        parameter.replace(default=Depends(actor_provider))
        if parameter.name in actor_names
        else parameter
        for parameter in parameters
    ]

    async def endpoint(**kwargs: object) -> object:
        return await handler(**kwargs)

    endpoint.__name__ = f"screen_{spec.id.replace('/', '_')}"
    endpoint.__signature__ = signature.replace(  # pyright: ignore[reportFunctionMemberAccess]
        parameters=bound, return_annotation=hints.get("return", signature.return_annotation)
    )
    return endpoint


def _screen_authorization_dependency(
    spec: ScreenSpec,
    actor_provider: ActorProvider,
    route_authorizer: RouteAuthorizer | None,
) -> Callable[..., Awaitable[None]]:
    actor_dependency = Depends(actor_provider)

    async def authorize(actor: ActorContext = actor_dependency) -> None:
        if route_authorizer is not None:
            route_authorizer.check_screen(spec, actor)

    return authorize


def mount_registry_routes(
    app: FastAPI,
    *,
    registry: Registry,
    executor: CommandExecutor,
    actor_provider: ActorProvider,
    limiter: InProcessRateLimiter,
    session_effects: SessionEffects | None = None,
    route_authorizer: RouteAuthorizer | None = None,
) -> None:
    for spec in registry.commands.values():
        if not spec.expose_http:
            continue
        endpoint, _request_model, response_model = _command_endpoint(
            spec, executor, actor_provider, limiter, session_effects, route_authorizer
        )
        app.add_api_route(
            f"/api/v1/commands/{spec.name}",
            endpoint,
            methods=["POST"],
            response_model=response_model,
        )

    for spec in registry.screens.values():
        authorize = _screen_authorization_dependency(
            spec, actor_provider, route_authorizer
        )
        app.add_api_route(
            f"/api/v1/screens/{spec.id}",
            _screen_endpoint(spec, actor_provider),
            methods=["GET"],
            dependencies=[Depends(authorize)],
        )
