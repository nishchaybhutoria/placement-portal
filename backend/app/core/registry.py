"""Typed command and screen registries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.core.plan import Plan, Rejection
from app.domain.shared import RuleDomain

Loader = Callable[..., Awaitable[object]]
Decider = Callable[..., Plan | Rejection]
ScreenHandler = Callable[..., Awaitable[object]]
#: ``admin_or_system`` is the one policy naming two callers, and it exists for
#: the one command that genuinely has two: the consistency checker runs nightly
#: as the worker and on demand from ``admin/findings`` (the design review section 4.36).
#: Widening ``system`` itself would have opened every worker-internal command to
#: administrators, which is the opposite of what that reversal asked for.
type ActorPolicy = Literal[
    "anonymous",
    "authenticated",
    "student",
    "staff",
    "admin",
    "admin_or_system",
    "system",
    "test",
]
type ScopePolicy = Literal["none", "cycle"]


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    actor: ActorPolicy
    scope: ScopePolicy
    loader: Loader
    decide: Decider
    rule_domains: tuple[RuleDomain, ...]
    spec_ids: tuple[str, ...]
    rate_limit: str | None
    execution_mode: Literal["single", "bulk"]
    expose_http: bool
    session_effect: Literal["establish", "clear"] | None


@dataclass(frozen=True, slots=True)
class ScreenSpec:
    id: str
    roles: tuple[str, ...]
    handler: ScreenHandler


class Registry:
    def __init__(self) -> None:
        self.commands: dict[str, CommandSpec] = {}
        self.screens: dict[str, ScreenSpec] = {}

    def command(
        self,
        *,
        name: str,
        input_model: type[BaseModel],
        output_model: type[BaseModel],
        actor: ActorPolicy,
        scope: ScopePolicy,
        loader: Loader,
        rule_domains: tuple[RuleDomain, ...],
        spec_ids: tuple[str, ...],
        rate_limit: str | None = None,
        execution_mode: Literal["single", "bulk"] = "single",
        expose_http: bool = True,
        session_effect: Literal["establish", "clear"] | None = None,
    ) -> Callable[[Decider], Decider]:
        def decorate(decide: Decider) -> Decider:
            if name in self.commands:
                raise ValueError(f"Command already registered: {name}")
            self.commands[name] = CommandSpec(
                name=name,
                input_model=input_model,
                output_model=output_model,
                actor=actor,
                scope=scope,
                loader=loader,
                decide=decide,
                rule_domains=rule_domains,
                spec_ids=spec_ids,
                rate_limit=rate_limit,
                execution_mode=execution_mode,
                expose_http=expose_http,
                session_effect=session_effect,
            )
            return decide

        return decorate

    def screen(
        self, *, id: str, roles: tuple[str, ...]
    ) -> Callable[[ScreenHandler], ScreenHandler]:
        def decorate(handler: ScreenHandler) -> ScreenHandler:
            if id in self.screens:
                raise ValueError(f"Screen already registered: {id}")
            self.screens[id] = ScreenSpec(id=id, roles=roles, handler=handler)
            return handler

        return decorate


registry = Registry()
command = registry.command
screen = registry.screen
