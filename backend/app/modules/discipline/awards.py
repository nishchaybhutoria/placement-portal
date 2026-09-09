"""Awarding strikes and converting them into penalties (Behavior DIS).

One implementation, called from two places.  ``award_strike`` awards one by
hand and ``finalize_round`` awards one per absentee, and a strike from either
source must convert on exactly the same rule -- so the conversion lives here
rather than in each caller (the design review section 4.25).

Conversion itself is M5's ``domain/discipline.maybe_convert``: this module
loads the enrollment's standing strikes, hands them over, and turns the groups
it returns into rows.  Nothing here decides *whether* a threshold is complete.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.errors import PENALTY_ALREADY_REVOKED, STRIKE_ALREADY_REVOKED
from app.core.plan import Deferred, Reason, StateOp
from app.domain.discipline import PenaltyState, StrikeState, maybe_convert
from app.domain.policy import resolve_policy
from app.domain.shared import CycleKind, StrikeSource

_STANDING = """
    SELECT
        e.id AS enrollment_id, u.email, u.full_name, e.roll_number,
        s.id AS strike_id, s.reason, s.source, s.created_at, s.updated_at,
        s.awarded_by, awarder.full_name AS awarded_by_name,
        s.is_active, s.consumed_by_penalty_id
    FROM enrollments e
    JOIN users u ON u.id = e.user_id
    LEFT JOIN strikes s ON s.enrollment_id = e.id
    LEFT JOIN users awarder ON awarder.id = s.awarded_by
    WHERE e.id = ANY(:enrollment_ids)
    ORDER BY e.id, s.created_at, s.id
"""

_PENALTIES = """
    SELECT
        p.id, p.enrollment_id, p.reasons, p.from_strikes, p.is_active,
        p.created_at, p.created_by, creator.full_name AS created_by_name,
        p.revoked_at, p.revoked_by, revoker.full_name AS revoked_by_name
    FROM penalties p
    LEFT JOIN users creator ON creator.id = p.created_by
    LEFT JOIN users revoker ON revoker.id = p.revoked_by
    WHERE p.enrollment_id = ANY(:enrollment_ids)
    ORDER BY p.enrollment_id, p.created_at, p.id
"""

_LOCK = """
    SELECT 1 FROM enrollments WHERE id = ANY(:enrollment_ids) FOR UPDATE
"""


@dataclass(frozen=True, slots=True)
class StrikeIntent:
    """One strike to award: whose, why, and where it came from."""

    enrollment_id: UUID
    reason: str
    source: StrikeSource


@dataclass(frozen=True, slots=True)
class StrikeRow:
    """A persisted strike, carrying what a screen has to show about it."""

    id: UUID
    enrollment_id: UUID
    reason: str
    source: StrikeSource
    created_at: datetime
    updated_at: datetime
    awarded_by: UUID | None
    awarded_by_name: str | None
    is_active: bool
    consumed_by_penalty_id: UUID | None

    def state(self) -> StrikeState:
        return StrikeState(
            id=self.id,
            reason=self.reason,
            created_at=self.created_at,
            is_active=self.is_active,
            consumed_by_penalty_id=self.consumed_by_penalty_id,
        )


@dataclass(frozen=True, slots=True)
class PenaltyRow:
    id: UUID
    enrollment_id: UUID
    reasons: str
    from_strikes: bool
    created_at: datetime
    created_by: UUID | None
    created_by_name: str | None
    is_active: bool
    revoked_at: datetime | None
    revoked_by: UUID | None
    revoked_by_name: str | None

    def state(self) -> PenaltyState:
        return PenaltyState(
            id=self.id, from_strikes=self.from_strikes, is_active=self.is_active
        )


@dataclass(frozen=True, slots=True)
class EnrollmentDiscipline:
    """One enrollment's standing record, as the loader read it."""

    enrollment_id: UUID
    email: str
    full_name: str
    roll_number: str | None
    strikes: tuple[StrikeRow, ...]
    penalties: tuple[PenaltyRow, ...]

    def active_strikes(self) -> int:
        return sum(1 for strike in self.strikes if strike.is_active)

    def active_penalties(self) -> int:
        return sum(1 for penalty in self.penalties if penalty.is_active)


@dataclass(slots=True)
class AwardOutcome:
    """What awarding a set of strikes does, before it does it."""

    state_ops: list[StateOp] = field(default_factory=list)
    deferred: list[Deferred] = field(default_factory=list)
    #: Per-enrollment report, identical in preview and execution.  Carries no
    #: generated id: a dry run and its execution mint different uuids, and the
    #: preview-parity harness compares what they both produced.
    rows: list[dict[str, object]] = field(default_factory=list)


def award_direct_penalty(
    record: EnrollmentDiscipline,
    *,
    reasons: str,
    actor_user_id: UUID | None,
) -> AwardOutcome:
    """Build M11's direct-penalty consequence for commands that chain it.

    ``award_penalty`` and OFR-5 termination both use this fragment.  Keeping
    the row and notification here prevents a chained intervention from growing
    a second, subtly different definition of a direct penalty.
    """
    return AwardOutcome(
        state_ops=[
            StateOp(
                op="insert",
                model="penalties",
                values={
                    "id": uuid4(),
                    "enrollment_id": record.enrollment_id,
                    "reasons": reasons,
                    "from_strikes": False,
                    "is_active": True,
                    "created_by": actor_user_id,
                },
            )
        ],
        deferred=[
            Deferred(
                task="deliver_notification",
                args={
                    "event_key": "penalty_added",
                    "recipient": record.email,
                    "context": {"student": record.full_name, "reasons": reasons},
                },
            )
        ],
        rows=[
            {
                "enrollment_id": str(record.enrollment_id),
                "full_name": record.full_name,
                "penalty_active": True,
            }
        ],
    )


def strike_revocable(strike: StrikeRow) -> Reason | None:
    """Why this strike cannot be revoked, or None.

    The screen asks it to decide whether to offer the control and the command
    asks it before acting, so a Revoke button that appears is one that works
    (the design review section 4.22).
    """
    if not strike.is_active:
        return Reason(
            code=STRIKE_ALREADY_REVOKED,
            human="That strike is already revoked",
            path="strike_id",
        )
    return None


def penalty_revocable(penalty: PenaltyRow) -> Reason | None:
    """Why this penalty cannot be revoked, or None."""
    if not penalty.is_active:
        return Reason(
            code=PENALTY_ALREADY_REVOKED,
            human="That penalty is already revoked",
            path="penalty_id",
        )
    return None


async def lock_enrollments(tx: AsyncSession, enrollment_ids: Sequence[UUID]) -> None:
    """Take the row lock conversion is judged under (CONTRIBUTING.md invariant 9).

    Conversion counts active unconsumed strikes against a threshold, so two
    concurrent awards must not both read "one strike" and both decline to
    convert.  The enrollment row is the mutex because strikes and penalties are
    both keyed by it.
    """
    if enrollment_ids:
        await tx.execute(sa.text(_LOCK), {"enrollment_ids": list(enrollment_ids)})


async def load_discipline(
    tx: AsyncConnection | AsyncSession, enrollment_ids: Sequence[UUID]
) -> dict[UUID, EnrollmentDiscipline]:
    """Every strike and penalty standing against each enrollment."""
    if not enrollment_ids:
        return {}
    ids = list(enrollment_ids)
    strike_rows = (
        await tx.execute(sa.text(_STANDING), {"enrollment_ids": ids})
    ).mappings().all()
    penalty_rows = (
        await tx.execute(sa.text(_PENALTIES), {"enrollment_ids": ids})
    ).mappings().all()

    penalties: dict[UUID, list[PenaltyRow]] = {}
    for row in penalty_rows:
        enrollment_id = UUID(str(row["enrollment_id"]))
        penalties.setdefault(enrollment_id, []).append(
            PenaltyRow(
                id=UUID(str(row["id"])),
                enrollment_id=enrollment_id,
                reasons=str(row["reasons"]),
                from_strikes=bool(row["from_strikes"]),
                created_at=row["created_at"],
                created_by=(
                    UUID(str(row["created_by"]))
                    if row["created_by"] is not None
                    else None
                ),
                created_by_name=(
                    str(row["created_by_name"])
                    if row["created_by_name"] is not None
                    else None
                ),
                is_active=bool(row["is_active"]),
                revoked_at=row["revoked_at"],
                revoked_by=(
                    UUID(str(row["revoked_by"]))
                    if row["revoked_by"] is not None
                    else None
                ),
                revoked_by_name=(
                    str(row["revoked_by_name"])
                    if row["revoked_by_name"] is not None
                    else None
                ),
            )
        )

    found: dict[UUID, EnrollmentDiscipline] = {}
    strikes: dict[UUID, list[StrikeRow]] = {}
    identity: dict[UUID, tuple[str, str, str | None]] = {}
    for row in strike_rows:
        enrollment_id = UUID(str(row["enrollment_id"]))
        identity[enrollment_id] = (
            str(row["email"]),
            str(row["full_name"]),
            str(row["roll_number"]) if row["roll_number"] else None,
        )
        if row["strike_id"] is None:
            continue
        strikes.setdefault(enrollment_id, []).append(
            StrikeRow(
                id=UUID(str(row["strike_id"])),
                enrollment_id=enrollment_id,
                reason=str(row["reason"]),
                source=StrikeSource(row["source"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                awarded_by=(
                    UUID(str(row["awarded_by"]))
                    if row["awarded_by"] is not None
                    else None
                ),
                awarded_by_name=(
                    str(row["awarded_by_name"])
                    if row["awarded_by_name"] is not None
                    else None
                ),
                is_active=bool(row["is_active"]),
                consumed_by_penalty_id=(
                    UUID(str(row["consumed_by_penalty_id"]))
                    if row["consumed_by_penalty_id"] is not None
                    else None
                ),
            )
        )
    for enrollment_id, (email, full_name, roll_number) in identity.items():
        found[enrollment_id] = EnrollmentDiscipline(
            enrollment_id=enrollment_id,
            email=email,
            full_name=full_name,
            roll_number=roll_number,
            strikes=tuple(strikes.get(enrollment_id, ())),
            penalties=tuple(penalties.get(enrollment_id, ())),
        )
    return found


async def resolve_threshold(tx: AsyncSession) -> int | None:
    """The global `strikes_per_penalty` (DIS: default 2, blank disables).

    Read through ``resolve_policy`` rather than off the row, so the documented
    default and its validation stay in one place.  The cycle kind is irrelevant
    here -- this knob is global, and M11 is its first reader.
    """
    rows = (
        await tx.execute(sa.text("SELECT key, value FROM settings"))
    ).mappings().all()
    settings = {str(row["key"]): row["value"] for row in rows}
    return resolve_policy(CycleKind.PLACEMENT, settings=settings).strikes_per_penalty.value


def award_strikes(
    intents: Sequence[StrikeIntent],
    standing: Mapping[UUID, EnrollmentDiscipline],
    *,
    threshold: int | None,
    now: datetime,
    actor_user_id: UUID | None,
) -> AwardOutcome:
    """Insert the strikes, then convert every complete threshold (DIS)."""
    outcome = AwardOutcome()
    by_enrollment: dict[UUID, list[StrikeIntent]] = {}
    for intent in intents:
        by_enrollment.setdefault(intent.enrollment_id, []).append(intent)

    for enrollment_id, awarded in by_enrollment.items():
        record = standing[enrollment_id]
        minted: list[StrikeState] = []
        for intent in awarded:
            strike_id = uuid4()
            outcome.state_ops.append(
                StateOp(
                    op="insert",
                    model="strikes",
                    values={
                        "id": strike_id,
                        "enrollment_id": enrollment_id,
                        "reason": intent.reason,
                        "source": intent.source.value,
                        "awarded_by": actor_user_id,
                        "is_active": True,
                    },
                )
            )
            # Ordering inside one award has to be stable for conversion to be
            # deterministic, and every row lands on the same `now`.
            minted.append(
                StrikeState(
                    id=strike_id,
                    reason=intent.reason,
                    created_at=now,
                    is_active=True,
                    consumed_by_penalty_id=None,
                )
            )

        snapshot = tuple(strike.state() for strike in record.strikes) + tuple(minted)
        conversions = maybe_convert(snapshot, threshold)
        total = record.active_strikes() + len(minted)

        for group in conversions:
            penalty_id = uuid4()
            outcome.state_ops.append(
                StateOp(
                    op="insert",
                    model="penalties",
                    values={
                        "id": penalty_id,
                        "enrollment_id": enrollment_id,
                        "reasons": group.reasons,
                        "from_strikes": True,
                        "is_active": True,
                        "created_by": actor_user_id,
                    },
                )
            )
            for strike_id in group.strike_ids:
                outcome.state_ops.append(
                    StateOp(
                        op="update",
                        model="strikes",
                        values={"consumed_by_penalty_id": penalty_id},
                        where={"id": strike_id},
                    )
                )
            outcome.deferred.append(
                Deferred(
                    task="deliver_notification",
                    args={
                        "event_key": "penalty_added",
                        "recipient": record.email,
                        "context": {"student": record.full_name, "reasons": group.reasons},
                    },
                )
            )

        for intent in awarded:
            outcome.deferred.append(
                Deferred(
                    task="deliver_notification",
                    args={
                        "event_key": "strike_added",
                        "recipient": record.email,
                        "context": {
                            "student": record.full_name,
                            "reason": intent.reason,
                            "total": total,
                        },
                    },
                )
            )

        outcome.rows.append(
            {
                "enrollment_id": str(enrollment_id),
                "full_name": record.full_name,
                "roll_number": record.roll_number,
                "strikes_awarded": len(awarded),
                "strike_total": total,
                "penalties_created": len(conversions),
            }
        )
    return outcome
