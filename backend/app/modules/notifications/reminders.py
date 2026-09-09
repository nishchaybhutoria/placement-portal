"""Idempotent deadline and round reminder commands (Behavior NTF)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan import ActorContext, Deferred, Plan, Rejection, ScopeIds, StateOp
from app.core.registry import Registry
from app.modules.applications.verdict import (
    APPLY_RULE_DOMAINS,
    compute_verdict,
    load_cycle_header,
    load_gate_overrides,
    load_rule_labels,
    load_student_context,
    student_job_query,
)
from app.modules.notifications.wording import format_time, or_absent

_DEADLINE_WINDOW = timedelta(minutes=30)
# SPEC-GAP: LLD section 12 says only "offset window" for a six-hourly round
# cron, without giving its width.  Half the cadence avoids both gaps and overlap;
# reminder_sends remains the correctness backstop at the exact boundary.
_ROUND_WINDOW = timedelta(hours=3)
_DEADLINE_JOB = student_job_query("j.id = :job_id", published_only=False)


class SendDeadlineRemindersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_at: datetime | None = None


class SendRoundRemindersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_at: datetime | None = None


class ReminderSummary(BaseModel):
    queued: int
    reminders: list[dict[str, object]]


@dataclass(frozen=True, slots=True)
class ReminderIntent:
    id: UUID
    kind: str
    dedup_key: str
    event_key: str
    recipient: str
    context: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReminderState:
    scope_ids: ScopeIds
    run_at: datetime
    intents: tuple[ReminderIntent, ...]


async def _clock(tx: AsyncSession, supplied: datetime | None) -> datetime:
    if supplied is not None:
        return supplied
    return cast(datetime, await tx.scalar(sa.select(sa.func.now())))


async def _already_sent(tx: AsyncSession, dedup_key: str) -> bool:
    return bool(
        await tx.scalar(
            sa.text("SELECT EXISTS (SELECT 1 FROM reminder_sends WHERE dedup_key = :key)"),
            {"key": dedup_key},
        )
    )


async def _load_deadline_reminders(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ReminderState:
    if not isinstance(input_value, SendDeadlineRemindersInput):
        raise TypeError("send_deadline_reminders requires SendDeadlineRemindersInput")
    run_at = await _clock(tx, input_value.run_at)
    query = """
        SELECT j.id AS job_id, j.cycle_id, cp.deadline_reminder_hours,
               e.id AS enrollment_id, u.email, u.full_name,
               j.title AS job_title, company.name AS company_name
        FROM jobs j
        JOIN companies company ON company.id = j.company_id
        JOIN cycle_policies cp ON cp.cycle_id = j.cycle_id
        JOIN cycle_memberships m ON m.cycle_id = j.cycle_id AND m.status = 'active'
        JOIN enrollments e ON e.id = m.enrollment_id
        JOIN users u ON u.id = e.user_id AND u.is_active
        WHERE j.application_deadline IS NOT NULL
          AND j.application_deadline BETWEEN
              CAST(:window_start AS timestamptz)
                  + cp.deadline_reminder_hours * interval '1 hour'
              AND CAST(:window_end AS timestamptz)
                  + cp.deadline_reminder_hours * interval '1 hour'
          AND NOT EXISTS (
              SELECT 1 FROM applications a
              WHERE a.job_id = j.id AND a.enrollment_id = e.id
          )
        ORDER BY j.id, e.id
    """
    if lock:
        query += " FOR UPDATE OF j, m"
    candidates = (
        (
            await tx.execute(
                sa.text(query),
                {
                    "window_start": run_at - _DEADLINE_WINDOW,
                    "window_end": run_at + _DEADLINE_WINDOW,
                },
            )
        )
        .mappings()
        .all()
    )

    intents: list[ReminderIntent] = []
    for candidate in candidates:
        cycle_id = cast(UUID, candidate["cycle_id"])
        enrollment_id = cast(UUID, candidate["enrollment_id"])
        job_id = cast(UUID, candidate["job_id"])
        # Re-read every gate and the rule after taking the authoritative member
        # and job locks.  No verdict column or earlier application decision is
        # consulted: ELG-1 binds reminders to the live profile at this instant.
        cycle = await load_cycle_header(tx, cycle_id)
        if cycle is None:
            continue
        context = await load_student_context(
            tx, cycle=cycle, enrollment_id=enrollment_id, lock=lock
        )
        job = (
            (
                await tx.execute(
                    sa.text(_DEADLINE_JOB),
                    {"job_id": job_id, "enrollment_id": enrollment_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if job is None:
            continue
        labels = await load_rule_labels(
            tx, context, [cast("dict[str, object] | None", job["eligibility_rule"])]
        )
        overrides = await load_gate_overrides(
            tx,
            scope_ids=ScopeIds(
                cycle_id=cycle_id,
                job_id=job_id,
                enrollment_id=enrollment_id,
            ),
        )
        if not compute_verdict(context, job, labels=labels, overrides=overrides).eligible:
            continue
        dedup_key = f"deadline:{job_id}:{enrollment_id}"
        if await _already_sent(tx, dedup_key):
            continue
        intents.append(
            ReminderIntent(
                id=uuid5(NAMESPACE_URL, f"cds:reminder:{dedup_key}"),
                kind="deadline",
                dedup_key=dedup_key,
                event_key="deadline_reminder",
                recipient=str(candidate["email"]),
                context={
                    "student": str(candidate["full_name"]),
                    "job": str(candidate["job_title"]),
                    "company": str(candidate["company_name"]),
                    "hours_left": int(candidate["deadline_reminder_hours"]),
                    "cycle_id": str(cycle_id),
                    "job_id": str(job_id),
                    "enrollment_id": str(enrollment_id),
                },
            )
        )
    return ReminderState(scope_ids=ScopeIds(), run_at=run_at, intents=tuple(intents))


async def _load_round_reminders(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> ReminderState:
    if not isinstance(input_value, SendRoundRemindersInput):
        raise TypeError("send_round_reminders requires SendRoundRemindersInput")
    run_at = await _clock(tx, input_value.run_at)
    query = """
        SELECT s.id AS round_state_id, s.application_id, s.round_id,
               a.enrollment_id, j.id AS job_id, j.cycle_id,
               u.email, u.full_name, j.title AS job_title, r.name AS round_name,
               COALESCE(s.venue_override, r.venue) AS effective_venue,
               COALESCE(s.scheduled_at_override, r.scheduled_at) AS effective_schedule
        FROM application_round_states s
        JOIN applications a ON a.id = s.application_id
        JOIN job_rounds r ON r.id = s.round_id
        JOIN jobs j ON j.id = a.job_id
        JOIN cycle_memberships m
          ON m.cycle_id = j.cycle_id AND m.enrollment_id = a.enrollment_id
        JOIN enrollments e ON e.id = a.enrollment_id
        JOIN users u ON u.id = e.user_id AND u.is_active
        JOIN cycle_policies cp ON cp.cycle_id = j.cycle_id
        WHERE a.status = 'in_progress'
          AND a.current_round_id = s.round_id
          AND s.result IN ('pending', 'waitlisted')
          AND m.status = 'active'
          AND COALESCE(s.scheduled_at_override, r.scheduled_at) BETWEEN
              CAST(:window_start AS timestamptz)
                  + cp.round_reminder_hours * interval '1 hour'
              AND CAST(:window_end AS timestamptz)
                  + cp.round_reminder_hours * interval '1 hour'
        ORDER BY s.round_id, a.enrollment_id, s.id
    """
    if lock:
        query += " FOR UPDATE OF s, a, m"
    candidates = (
        (
            await tx.execute(
                sa.text(query),
                {
                    "window_start": run_at - _ROUND_WINDOW,
                    "window_end": run_at + _ROUND_WINDOW,
                },
            )
        )
        .mappings()
        .all()
    )

    intents: list[ReminderIntent] = []
    for row in candidates:
        # The locked query itself is the fire-time relevance re-check: only an
        # in-progress application whose current pointer is this round survives.
        # Rejected, withdrawn, advanced-away, or membership-exit rows do not.
        round_id = cast(UUID, row["round_id"])
        enrollment_id = cast(UUID, row["enrollment_id"])
        dedup_key = f"round:{round_id}:{enrollment_id}"
        if await _already_sent(tx, dedup_key):
            continue
        schedule = cast(datetime, row["effective_schedule"])
        cycle_id = cast(UUID, row["cycle_id"])
        job_id = cast(UUID, row["job_id"])
        intents.append(
            ReminderIntent(
                id=uuid5(NAMESPACE_URL, f"cds:reminder:{dedup_key}"),
                kind="round",
                dedup_key=dedup_key,
                event_key="round_reminder",
                recipient=str(row["email"]),
                context={
                    "student": str(row["full_name"]),
                    "job": str(row["job_title"]),
                    "round": str(row["round_name"]),
                    "venue": or_absent(row["effective_venue"]),
                    "time": format_time(schedule),
                    "cycle_id": str(cycle_id),
                    "job_id": str(job_id),
                    "enrollment_id": str(enrollment_id),
                    "application_id": str(cast(UUID, row["application_id"])),
                    "round_id": str(round_id),
                },
            )
        )
    return ReminderState(scope_ids=ScopeIds(), run_at=run_at, intents=tuple(intents))


def _decide_reminders(
    _input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """NTF: persist dedup markers and email intents in the same transaction."""
    if not isinstance(state, ReminderState):
        raise TypeError("Invalid reminder decision state")
    return Plan(
        state_ops=[
            StateOp(
                op="insert",
                model="reminder_sends",
                values={"id": intent.id, "kind": intent.kind, "dedup_key": intent.dedup_key},
            )
            for intent in state.intents
        ],
        events=[],
        deferred=[
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": intent.event_key,
                    "recipient": intent.recipient,
                    "context": intent.context,
                },
            )
            for intent in state.intents
        ],
        audit=None,
        summary={
            "queued": len(state.intents),
            "reminders": [
                {
                    "kind": intent.kind,
                    "dedup_key": intent.dedup_key,
                    "recipient": intent.recipient,
                    "event_key": intent.event_key,
                }
                for intent in state.intents
            ],
        },
    )


def register_reminder_commands(registry: Registry) -> None:
    registry.command(
        name="send_deadline_reminders",
        input_model=SendDeadlineRemindersInput,
        output_model=ReminderSummary,
        actor="system",
        scope="none",
        loader=_load_deadline_reminders,
        rule_domains=APPLY_RULE_DOMAINS,
        spec_ids=("NTF", "ELG-1", "ELG-3"),
        expose_http=False,
    )(_decide_reminders)
    registry.command(
        name="send_round_reminders",
        input_model=SendRoundRemindersInput,
        output_model=ReminderSummary,
        actor="system",
        scope="none",
        loader=_load_round_reminders,
        rule_domains=(),
        spec_ids=("NTF", "RND-4"),
        expose_http=False,
    )(_decide_reminders)
