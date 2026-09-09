"""Immutable command plans and executor result contracts from LLD section 5."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from app.domain.shared import EventType


@dataclass(frozen=True, slots=True)
class Reason:
    code: str
    human: str
    path: str | None = None


@dataclass(frozen=True, slots=True)
class StateOp:
    op: Literal["insert", "update", "delete"]
    model: str
    values: dict[str, object]
    where: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class Event:
    application_id: UUID | None
    event_type: EventType
    from_status: str | None
    to_status: str | None
    from_round: UUID | None
    to_round: UUID | None
    reason: str | None
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class Deferred:
    task: str
    args: dict[str, object]
    schedule_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Plan:
    state_ops: list[StateOp]
    events: list[Event]
    deferred: list[Deferred]
    audit: dict[str, object] | None
    summary: dict[str, object]


@dataclass(frozen=True, slots=True)
class Rejection:
    reasons: list[Reason]


@dataclass(frozen=True, slots=True)
class Preview:
    summary: dict[str, object]
    events: list[Event]


@dataclass(frozen=True, slots=True)
class Result:
    summary: dict[str, object]
    events: list[Event]


@dataclass(frozen=True, slots=True)
class ScopeIds:
    cycle_id: UUID | None = None
    job_id: UUID | None = None
    enrollment_id: UUID | None = None
    application_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ActorContext:
    principal_id: str
    user_id: UUID | None = None
    role: str | None = None
    session_id: UUID | None = None
    current_enrollment_id: UUID | None = None
    coordinated_cycle_ids: tuple[UUID, ...] = ()
    email: str | None = None
    full_name: str | None = None
    profile_declared: bool = False
    is_system: bool = False
    is_test_harness: bool = False


class LoadedState(Protocol):
    @property
    def scope_ids(self) -> ScopeIds: ...
