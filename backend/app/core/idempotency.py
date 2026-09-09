"""Concurrency-safe idempotency reservations for command execution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import IDEMPOTENCY_CONFLICT, DomainRejection
from app.core.plan import Event, Reason, Rejection, Result, ScopeIds
from app.domain.shared import EventType
from app.modules.admin.models import IdempotencyKey


@dataclass(frozen=True, slots=True)
class Reservation:
    owned: bool
    cached: Result | None = None
    scope_ids: ScopeIds | None = None


def request_fingerprint(input_value: BaseModel) -> str:
    canonical = json.dumps(
        input_value.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _scope_payload(scope_ids: ScopeIds) -> dict[str, object]:
    return {
        "cycle_id": str(scope_ids.cycle_id) if scope_ids.cycle_id else None,
        "job_id": str(scope_ids.job_id) if scope_ids.job_id else None,
        "enrollment_id": str(scope_ids.enrollment_id) if scope_ids.enrollment_id else None,
        "application_id": str(scope_ids.application_id) if scope_ids.application_id else None,
    }


def _scope_from_payload(payload: dict[str, object]) -> ScopeIds:
    def value(name: str) -> UUID | None:
        raw = payload.get(name)
        return UUID(cast(str, raw)) if raw else None

    return ScopeIds(
        cycle_id=value("cycle_id"),
        job_id=value("job_id"),
        enrollment_id=value("enrollment_id"),
        application_id=value("application_id"),
    )


def _event_payload(event: Event) -> dict[str, object]:
    return {
        "application_id": str(event.application_id) if event.application_id else None,
        "event_type": event.event_type.value,
        "from_status": event.from_status,
        "to_status": event.to_status,
        "from_round": str(event.from_round) if event.from_round else None,
        "to_round": str(event.to_round) if event.to_round else None,
        "reason": event.reason,
        "payload": event.payload,
    }


def _event_from_payload(payload: dict[str, object]) -> Event:
    from uuid import UUID

    application_id = payload.get("application_id")
    from_round = payload.get("from_round")
    to_round = payload.get("to_round")
    return Event(
        application_id=UUID(cast(str, application_id)) if application_id else None,
        event_type=EventType(cast(str, payload["event_type"])),
        from_status=cast(str | None, payload.get("from_status")),
        to_status=cast(str | None, payload.get("to_status")),
        from_round=UUID(cast(str, from_round)) if from_round else None,
        to_round=UUID(cast(str, to_round)) if to_round else None,
        reason=cast(str | None, payload.get("reason")),
        payload=cast(dict[str, object], payload.get("payload", {})),
    )


async def reserve(
    tx: AsyncSession,
    key: str,
    command: str,
    *,
    principal_id: str,
    fingerprint: str,
) -> Reservation:
    statement = (
        insert(IdempotencyKey)
        .values(
            key=key,
            command=command,
            result={
                "status": "in_progress",
                "principal_id": principal_id,
                "request_fingerprint": fingerprint,
            },
        )
        .on_conflict_do_nothing(index_elements=[IdempotencyKey.key])
        .returning(IdempotencyKey.id)
    )
    reservation_id = await tx.scalar(statement)
    if reservation_id is not None:
        return Reservation(owned=True)

    row = (
        await tx.execute(
            select(IdempotencyKey.command, IdempotencyKey.result).where(
                IdempotencyKey.key == key
            )
        )
    ).one()
    existing_command = cast(str, row.command)
    envelope = cast(dict[str, object], row.result)
    if (
        existing_command != command
        or envelope.get("principal_id") != principal_id
        or envelope.get("request_fingerprint") != fingerprint
    ):
        raise DomainRejection(
            Rejection(
                reasons=[
                    Reason(
                        code=IDEMPOTENCY_CONFLICT,
                        human="Idempotency key does not match the original request",
                    )
                ]
            )
        )

    if envelope.get("status") != "complete":
        raise RuntimeError("Committed idempotency reservation is incomplete")
    summary = cast(dict[str, object], envelope["summary"])
    event_payloads = cast(list[dict[str, object]], envelope["events"])
    scope_payload = envelope.get("scope_ids")
    if not isinstance(scope_payload, dict):
        raise RuntimeError("Completed idempotency reservation has no scope snapshot")
    return Reservation(
        owned=False,
        cached=Result(
            summary=summary,
            events=[_event_from_payload(event) for event in event_payloads],
        ),
        scope_ids=_scope_from_payload(cast(dict[str, object], scope_payload)),
    )


async def complete(
    tx: AsyncSession,
    key: str,
    result: Result,
    *,
    principal_id: str,
    fingerprint: str,
    scope_ids: ScopeIds,
) -> None:
    envelope: dict[str, object] = {
        "status": "complete",
        "principal_id": principal_id,
        "request_fingerprint": fingerprint,
        "scope_ids": _scope_payload(scope_ids),
        "summary": result.summary,
        "events": [_event_payload(event) for event in result.events],
    }
    await tx.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.key == key)
        .values(result=envelope)
    )
