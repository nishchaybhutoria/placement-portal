"""The nightly consistency pass and the two finding verdicts (LLD section 12).

The checker is the backstop named in Behavior section 16 rule 4: it re-derives
what is derivable, asserts every invariant in ``checker.INVARIANTS``, and turns
drift into an administrator-visible finding carrying the compensating command.
It repairs nothing itself -- a checker that wrote fixes would be a second write
path around the executor, and a wrong repair at 03:00 is worse than a finding.

Re-run semantics, which are the part worth reading twice.  A finding's identity
is ``uuid5(invariant + subject)``, so the same drift seen on twenty nights is
one row rather than twenty.  On top of that identity:

* an **open** finding stays as it is;
* a **resolved** finding whose corruption is present again is re-opened, because
  "I fixed it" turning out to be untrue is news;
* a **dismissed** finding stays silent while the corruption persists -- that is
  what dismissing means -- but the moment the invariant holds again for that
  subject the row is marked resolved, so a *later* independent corruption of the
  same subject raises a fresh finding instead of being swallowed forever.

The purge at the end is the design review section 4.11 housekeeping riding on the same
nightly run: expired or revoked sessions, and reminder dedup rows older than 180
days.  It is bounded per run and reported separately, because it is hygiene and
not correctness, and nothing about the invariants should depend on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import FINDING_NOT_FOUND, FINDING_NOT_OPEN
from app.core.plan import (
    ActorContext,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.domain.shared import FindingStatus
from app.modules.admin.checker import (
    INVARIANTS,
    Invariant,
    Subject,
    detail_of,
    finding_id,
    subject_of,
    suggested_fix_for,
)

#: How many rows one nightly purge may remove per table.  Bounded because a
#: housekeeping delete must never be the reason the correctness pass times out;
#: whatever is left is taken by the next run.
PURGE_LIMIT = 5000
REMINDER_RETENTION_DAYS = 180


class RunConsistencyCheckerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_at: datetime | None = None


class ResolveFindingInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    finding_id: UUID
    #: Mandatory on both verdicts: a finding closed without a reason leaves the
    #: next administrator unable to tell a compensated corruption from one
    #: somebody decided to live with.
    reason: str

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("a reason is required")
        return value.strip()


class ConsistencyRunSummary(BaseModel):
    checked_invariants: int
    violations: int
    findings_opened: int
    findings_reopened: int
    findings_auto_resolved: int
    #: Per invariant, how many violating subjects it saw -- listed, never
    #: reduced to one number, because "seven findings" says nothing about which
    #: promise the system stopped keeping.
    by_invariant: list[dict[str, object]]
    sessions_purged: int
    reminder_sends_purged: int


class FindingVerdictSummary(BaseModel):
    finding_id: UUID
    invariant: str
    status: FindingStatus


@dataclass(frozen=True, slots=True)
class Violation:
    invariant: Invariant
    subject: Subject
    detail: str

    @property
    def id(self) -> UUID:
        return finding_id(self.invariant.id, self.subject)


@dataclass(frozen=True, slots=True)
class ExistingFinding:
    id: UUID
    invariant: str
    status: FindingStatus


@dataclass(frozen=True, slots=True)
class CheckerState:
    scope_ids: ScopeIds
    now: datetime
    violations: tuple[Violation, ...]
    existing: dict[UUID, ExistingFinding]
    expired_session_ids: tuple[UUID, ...] = ()
    stale_reminder_ids: tuple[UUID, ...] = ()
    counts: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FindingState:
    scope_ids: ScopeIds
    now: datetime
    row: sa.RowMapping | None


async def _load_checker(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> CheckerState:
    del lock  # every statement below is a read; nothing is decided on a locked row
    if not isinstance(input_value, RunConsistencyCheckerInput):
        raise TypeError("run_consistency_checker requires RunConsistencyCheckerInput")

    violations: list[Violation] = []
    counts: dict[str, int] = {}
    for invariant in INVARIANTS:
        rows = (await tx.execute(sa.text(invariant.sql))).mappings().all()
        counts[invariant.id] = len(rows)
        violations.extend(
            Violation(
                invariant=invariant,
                subject=subject_of(invariant, row),
                detail=detail_of(row),
            )
            for row in rows
        )

    # Every finding this run could touch: the ones it is about to raise, plus
    # every dismissed row whose subject may have healed since it was dismissed.
    existing_rows = (
        await tx.execute(
            sa.text(
                "SELECT id, invariant, status FROM consistency_findings "
                "WHERE id = ANY(:ids) OR status = 'dismissed'"
            ).bindparams(sa.bindparam("ids", type_=ARRAY(sa.Uuid()))),
            {"ids": [violation.id for violation in violations]},
        )
    ).mappings().all()
    existing = {
        cast(UUID, row["id"]): ExistingFinding(
            id=cast(UUID, row["id"]),
            invariant=str(row["invariant"]),
            status=FindingStatus(row["status"]),
        )
        for row in existing_rows
    }

    sessions = (
        await tx.scalars(
            sa.text(
                "SELECT id FROM sessions "
                "WHERE expires_at <= now() OR revoked_at IS NOT NULL "
                "ORDER BY id LIMIT :limit"
            ),
            {"limit": PURGE_LIMIT},
        )
    ).all()
    reminders = (
        await tx.scalars(
            sa.text(
                "SELECT id FROM reminder_sends "
                "WHERE created_at < now() - make_interval(days => :days) "
                "ORDER BY id LIMIT :limit"
            ),
            {"days": REMINDER_RETENTION_DAYS, "limit": PURGE_LIMIT},
        )
    ).all()

    return CheckerState(
        scope_ids=ScopeIds(),
        now=input_value.run_at
        or cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        violations=tuple(violations),
        existing=existing,
        expired_session_ids=tuple(cast("list[UUID]", list(sessions))),
        stale_reminder_ids=tuple(cast("list[UUID]", list(reminders))),
        counts=counts,
    )


def _decide_run_consistency_checker(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Assert every LLD section 12 invariant and record the drift (section 16)."""
    if not isinstance(input_value, RunConsistencyCheckerInput) or not isinstance(
        state, CheckerState
    ):
        raise TypeError("Invalid run_consistency_checker decision input")

    operations: list[StateOp] = []
    opened = 0
    reopened = 0
    still_violating: set[UUID] = set()

    for violation in state.violations:
        still_violating.add(violation.id)
        existing = state.existing.get(violation.id)
        fix = suggested_fix_for(violation.invariant.id)
        if existing is None:
            opened += 1
            operations.append(
                StateOp(
                    op="insert",
                    model="consistency_findings",
                    values={
                        "id": violation.id,
                        "invariant": violation.invariant.id,
                        "subject": violation.subject,
                        "detail": violation.detail,
                        "status": FindingStatus.OPEN.value,
                        "suggested_fix": fix.command if fix is not None else None,
                    },
                )
            )
        elif existing.status is FindingStatus.RESOLVED:
            reopened += 1
            operations.append(
                StateOp(
                    op="update",
                    model="consistency_findings",
                    values={
                        "status": FindingStatus.OPEN.value,
                        "resolved_at": None,
                        "detail": violation.detail,
                    },
                    where={"id": violation.id},
                )
            )

    # A dismissed finding whose invariant now holds is closed out, so the next
    # independent corruption of the same subject is raised as new rather than
    # being suppressed by a verdict about a different occurrence.
    healed = [
        item
        for item in state.existing.values()
        if item.status is FindingStatus.DISMISSED and item.id not in still_violating
    ]
    operations.extend(
        StateOp(
            op="update",
            model="consistency_findings",
            values={
                "status": FindingStatus.RESOLVED.value,
                "resolved_at": state.now,
            },
            where={"id": item.id},
        )
        for item in healed
    )

    operations.extend(
        StateOp(op="delete", model="sessions", values={}, where={"id": session_id})
        for session_id in state.expired_session_ids
    )
    operations.extend(
        StateOp(op="delete", model="reminder_sends", values={}, where={"id": reminder_id})
        for reminder_id in state.stale_reminder_ids
    )

    by_invariant = [
        {"invariant": invariant.id, "violations": state.counts.get(invariant.id, 0)}
        for invariant in INVARIANTS
    ]
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit={
            "subject_type": "consistency_run",
            "subject_id": None,
            "details": {
                "violations": len(state.violations),
                "findings_opened": opened,
                "findings_reopened": reopened,
                "findings_auto_resolved": len(healed),
                "sessions_purged": len(state.expired_session_ids),
                "reminder_sends_purged": len(state.stale_reminder_ids),
            },
        },
        summary={
            "checked_invariants": len(INVARIANTS),
            "violations": len(state.violations),
            "findings_opened": opened,
            "findings_reopened": reopened,
            "findings_auto_resolved": len(healed),
            "by_invariant": by_invariant,
            "sessions_purged": len(state.expired_session_ids),
            "reminder_sends_purged": len(state.stale_reminder_ids),
        },
    )


async def _load_finding(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> FindingState:
    if not isinstance(input_value, ResolveFindingInput):
        raise TypeError("A finding verdict requires ResolveFindingInput")
    row = (
        await tx.execute(
            sa.text(
                "SELECT id, invariant, subject, detail, status FROM consistency_findings "
                "WHERE id = :id" + (" FOR UPDATE" if lock else "")
            ),
            {"id": input_value.finding_id},
        )
    ).mappings().one_or_none()
    return FindingState(
        scope_ids=ScopeIds(),
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
        row=row,
    )


def _verdict(
    input_value: ResolveFindingInput,
    state: FindingState,
    *,
    status: FindingStatus,
    action: str,
) -> Plan | Rejection:
    if state.row is None:
        return Rejection(
            reasons=[
                Reason(
                    code=FINDING_NOT_FOUND,
                    human="The finding does not exist",
                    path="finding_id",
                )
            ]
        )
    if FindingStatus(state.row["status"]) is not FindingStatus.OPEN:
        return Rejection(
            reasons=[
                Reason(
                    code=FINDING_NOT_OPEN,
                    human=(
                        "This finding is already "
                        f"{str(state.row['status'])}"
                    ),
                    path="finding_id",
                )
            ]
        )

    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="consistency_findings",
                values={"status": status.value, "resolved_at": state.now},
                where={"id": input_value.finding_id},
            )
        ],
        events=[],
        deferred=[],
        audit={
            "subject_type": "consistency_finding",
            "subject_id": input_value.finding_id,
            "details": {
                "action": action,
                "invariant": str(state.row["invariant"]),
                "subject": state.row["subject"],
                "reason": input_value.reason,
            },
        },
        summary={
            "finding_id": str(input_value.finding_id),
            "invariant": str(state.row["invariant"]),
            "status": status.value,
        },
    )


def _decide_resolve_finding(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Record that the drift behind a finding has been compensated (section 16)."""
    if not isinstance(input_value, ResolveFindingInput) or not isinstance(
        state, FindingState
    ):
        raise TypeError("Invalid resolve_finding decision input")
    # Deliberately not re-checking the invariant here: the next nightly run
    # re-opens the finding if the corruption is still there, which is both
    # cheaper and more honest than asserting it from inside the verdict.
    return _verdict(
        input_value, state, status=FindingStatus.RESOLVED, action="resolve_finding"
    )


def _decide_dismiss_finding(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Record that a finding is not a problem worth compensating (section 16)."""
    if not isinstance(input_value, ResolveFindingInput) or not isinstance(
        state, FindingState
    ):
        raise TypeError("Invalid dismiss_finding decision input")
    return _verdict(
        input_value, state, status=FindingStatus.DISMISSED, action="dismiss_finding"
    )


def register_admin_commands(registry: Registry) -> None:
    registry.command(
        name="run_consistency_checker",
        input_model=RunConsistencyCheckerInput,
        output_model=ConsistencyRunSummary,
        # Nightly as the worker, on demand from `admin/findings`: an
        # administrator who has just compensated a finding needs to see it
        # clear rather than wait until 03:00 (the design review section 4.36).
        actor="admin_or_system",
        scope="none",
        loader=_load_checker,
        rule_domains=(),
        spec_ids=("INT-2", "S16"),
        rate_limit="10/min",
    )(_decide_run_consistency_checker)
    registry.command(
        name="resolve_finding",
        input_model=ResolveFindingInput,
        output_model=FindingVerdictSummary,
        actor="admin",
        scope="none",
        loader=_load_finding,
        rule_domains=(),
        spec_ids=("INT-1", "S16"),
        rate_limit="10/min",
    )(_decide_resolve_finding)
    registry.command(
        name="dismiss_finding",
        input_model=ResolveFindingInput,
        output_model=FindingVerdictSummary,
        actor="admin",
        scope="none",
        loader=_load_finding,
        rule_domains=(),
        spec_ids=("INT-1", "S16"),
        rate_limit="10/min",
    )(_decide_dismiss_finding)
