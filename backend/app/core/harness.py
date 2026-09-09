"""Explicitly opt-in command/screen fixtures for the M2 guarantee harness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan import ActorContext, Deferred, Plan, Rejection, ScopeIds
from app.core.registry import Registry


class PingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient: str
    schedule_at: datetime | None = None


class PingSummary(BaseModel):
    accepted: bool


class EchoSummary(BaseModel):
    message: str


@dataclass(frozen=True, slots=True)
class EmptyState:
    scope_ids: ScopeIds = ScopeIds()


async def _load_empty(
    _tx: AsyncSession, _input_value: BaseModel, *, lock: bool
) -> EmptyState:
    del lock
    return EmptyState()


def _decide_ping(
    input_value: PingInput,
    _state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Exercise transaction, audit, deferral, and preview parity for Behavior §16."""
    return Plan(
        state_ops=[],
        events=[],
        deferred=[
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "membership_restored",
                    "recipient": input_value.recipient,
                    "context": {
                        "source": "m2-harness",
                        "student": "Harness student",
                        "cycle": "Harness cycle",
                    },
                },
                schedule_at=input_value.schedule_at,
            )
        ],
        audit={"subject_type": "harness", "details": {"recipient": input_value.recipient}},
        summary={"accepted": True},
    )


def register_harness(registry: Registry) -> None:
    registry.command(
        name="ping",
        input_model=PingInput,
        output_model=PingSummary,
        actor="test",
        scope="none",
        loader=_load_empty,
        rule_domains=(),
        spec_ids=("§16",),
    )(_decide_ping)

    async def echo(message: str) -> EchoSummary:
        return EchoSummary(message=message)

    registry.screen(id="echo", roles=("test",))(echo)
