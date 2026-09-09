"""Resolve active scoped overrides with deterministic specificity precedence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.core.plan import ScopeIds
from app.domain.shared import RuleDomain, override_scope_combination, scope_name
from app.modules.overrides.models import Override

type OverrideConnection = AsyncSession | AsyncConnection

Specificity = Literal[
    "cycle",
    "job",
    "enrollment",
    "cycle+enrollment",
    "job+enrollment",
    "application",
]
SPECIFICITY_RANK: dict[Specificity, int] = {
    "cycle": 1,
    "job": 2,
    "enrollment": 3,
    "cycle+enrollment": 4,
    "job+enrollment": 5,
    "application": 6,
}

_SCOPE_ATTRS = {
    "cycle": "cycle_id",
    "job": "job_id",
    "enrollment": "enrollment_id",
    "application": "application_id",
}


@dataclass(frozen=True, slots=True)
class OverrideCandidate:
    id: UUID
    rule_domain: str
    allow: bool
    reason: str
    granted_by: UUID
    created_at: datetime
    expires_at: datetime | None
    cycle_id: UUID | None
    job_id: UUID | None
    enrollment_id: UUID | None
    application_id: UUID | None


@dataclass(frozen=True, slots=True)
class ApplicableOverride:
    id: UUID
    rule_domain: RuleDomain
    allow: bool
    reason: str
    specificity: Specificity
    granted_by: UUID
    expires_at: datetime | None


OverrideDisplayState = Literal["active", "expired", "shadowed"]


@dataclass(frozen=True, slots=True)
class ClassifiedOverride:
    """One relevant live or expired row as a subject page should describe it."""

    id: UUID
    rule_domain: RuleDomain
    allow: bool
    reason: str
    specificity: Specificity
    granted_by: UUID
    created_at: datetime
    expires_at: datetime | None
    state: OverrideDisplayState
    cycle_id: UUID | None
    job_id: UUID | None
    enrollment_id: UUID | None
    application_id: UUID | None


def _matching_specificity(
    row: OverrideCandidate, scope_ids: ScopeIds
) -> Specificity | None:
    """Return the row's rank only when every target column matches the subject."""
    combination = override_scope_combination(
        cycle_id=row.cycle_id,
        job_id=row.job_id,
        enrollment_id=row.enrollment_id,
        application_id=row.application_id,
    )
    if combination is None:
        # The database CHECK makes this unreachable.  Failing closed here keeps
        # a malformed row from being interpreted as a broader grant if the
        # service is ever pointed at a pre-migration schema.
        return None
    for target in combination:
        attribute = _SCOPE_ATTRS[target]
        if getattr(row, attribute) != getattr(scope_ids, attribute):
            return None
    name = scope_name(combination)
    return next(
        (item for item in SPECIFICITY_RANK if item == name),
        None,
    )


def _select_applicable(
    rows: list[OverrideCandidate],
    rule_domains: tuple[RuleDomain, ...],
    scope_ids: ScopeIds,
) -> tuple[ApplicableOverride, ...]:
    selected: list[ApplicableOverride] = []
    for domain in rule_domains:
        matches: list[tuple[OverrideCandidate, Specificity]] = []
        for row in rows:
            if row.rule_domain != domain.value:
                continue
            specificity = _matching_specificity(row, scope_ids)
            if specificity is not None:
                matches.append((row, specificity))
        if not matches:
            continue
        row, specificity = max(
            matches,
            key=lambda match: (
                SPECIFICITY_RANK[match[1]],
                not match[0].allow,
                match[0].created_at,
                match[0].id.int,
            ),
        )
        selected.append(
            ApplicableOverride(
                id=row.id,
                rule_domain=domain,
                allow=row.allow,
                reason=row.reason,
                specificity=specificity,
                granted_by=row.granted_by,
                expires_at=row.expires_at,
            )
        )
    return tuple(selected)


async def _candidates(
    tx: OverrideConnection,
    rule_domains: tuple[RuleDomain, ...],
    scope_ids: tuple[ScopeIds, ...],
    *,
    include_expired: bool,
) -> list[OverrideCandidate]:
    if not rule_domains or not scope_ids:
        return []

    application_ids = {
        scope.application_id for scope in scope_ids if scope.application_id is not None
    }
    enrollment_ids = {
        scope.enrollment_id for scope in scope_ids if scope.enrollment_id is not None
    }
    job_ids = {scope.job_id for scope in scope_ids if scope.job_id is not None}
    cycle_ids = {scope.cycle_id for scope in scope_ids if scope.cycle_id is not None}
    scope_filters: list[sa.ColumnElement[bool]] = []
    if application_ids:
        scope_filters.append(Override.application_id.in_(application_ids))
    if enrollment_ids:
        scope_filters.append(Override.enrollment_id.in_(enrollment_ids))
    if job_ids:
        scope_filters.append(Override.job_id.in_(job_ids))
    if cycle_ids:
        scope_filters.append(Override.cycle_id.in_(cycle_ids))
    if not scope_filters:
        return []

    predicates: list[sa.ColumnElement[bool]] = [
        Override.rule_domain.in_([domain.value for domain in rule_domains]),
        Override.is_active.is_(True),
        sa.or_(*scope_filters),
    ]
    if not include_expired:
        predicates.append(
            sa.or_(
                Override.expires_at.is_(None),
                Override.expires_at > sa.func.now(),
            )
        )
    rows = (
        await tx.execute(sa.select(Override.__table__).where(*predicates))
    ).mappings().all()
    return [
        OverrideCandidate(
            id=cast(UUID, row["id"]),
            rule_domain=str(row["rule_domain"]),
            allow=bool(row["allow"]),
            reason=str(row["reason"]),
            granted_by=cast(UUID, row["granted_by"]),
            created_at=cast(datetime, row["created_at"]),
            expires_at=cast("datetime | None", row["expires_at"]),
            cycle_id=cast("UUID | None", row["cycle_id"]),
            job_id=cast("UUID | None", row["job_id"]),
            enrollment_id=cast("UUID | None", row["enrollment_id"]),
            application_id=cast("UUID | None", row["application_id"]),
        )
        for row in rows
    ]


async def _active_candidates(
    tx: OverrideConnection,
    rule_domains: tuple[RuleDomain, ...],
    scope_ids: tuple[ScopeIds, ...],
) -> list[OverrideCandidate]:
    return await _candidates(
        tx, rule_domains, scope_ids, include_expired=False
    )


async def applicable(
    tx: OverrideConnection,
    rule_domains: tuple[RuleDomain, ...],
    scope_ids: ScopeIds,
) -> tuple[ApplicableOverride, ...]:
    rows = await _active_candidates(tx, rule_domains, (scope_ids,))
    return _select_applicable(rows, rule_domains, scope_ids)


async def applicable_many[ScopeKey](
    tx: OverrideConnection,
    rule_domains: tuple[RuleDomain, ...],
    scopes: Mapping[ScopeKey, ScopeIds],
) -> dict[ScopeKey, tuple[ApplicableOverride, ...]]:
    """Resolve many complete subjects with one override query.

    Bulk loaders judge each row against its enrollment/application scope.  A
    query per row would turn the 500-row command chunk into 500 extra database
    round trips, so candidates are fetched once and the ordinary precedence
    rule is then applied independently to every subject.
    """
    rows = await _active_candidates(tx, rule_domains, tuple(scopes.values()))
    return {
        key: _select_applicable(rows, rule_domains, scope_ids)
        for key, scope_ids in scopes.items()
    }


def _classify(
    rows: list[OverrideCandidate],
    rule_domains: tuple[RuleDomain, ...],
    scopes: tuple[ScopeIds, ...],
    now: datetime,
) -> tuple[ClassifiedOverride, ...]:
    relevant: dict[UUID, tuple[OverrideCandidate, Specificity]] = {}
    winner_ids: set[UUID] = set()
    for scope_ids in scopes:
        live: list[OverrideCandidate] = []
        for row in rows:
            specificity = _matching_specificity(row, scope_ids)
            if specificity is None:
                continue
            relevant[row.id] = (row, specificity)
            if row.expires_at is None or row.expires_at > now:
                live.append(row)
        winner_ids.update(
            item.id for item in _select_applicable(live, rule_domains, scope_ids)
        )

    classified = [
        ClassifiedOverride(
            id=row.id,
            rule_domain=RuleDomain(row.rule_domain),
            allow=row.allow,
            reason=row.reason,
            specificity=specificity,
            granted_by=row.granted_by,
            created_at=row.created_at,
            expires_at=row.expires_at,
            state=(
                "expired"
                if row.expires_at is not None and row.expires_at <= now
                else "active"
                if row.id in winner_ids
                else "shadowed"
            ),
            cycle_id=row.cycle_id,
            job_id=row.job_id,
            enrollment_id=row.enrollment_id,
            application_id=row.application_id,
        )
        for row, specificity in relevant.values()
    ]
    state_rank = {"active": 0, "shadowed": 1, "expired": 2}
    return tuple(
        sorted(
            classified,
            key=lambda item: (
                state_rank[item.state],
                item.rule_domain.value,
                -SPECIFICITY_RANK[item.specificity],
                -item.created_at.timestamp(),
                -item.id.int,
            ),
        )
    )


async def classified_many(
    tx: OverrideConnection,
    rule_domains: tuple[RuleDomain, ...],
    scopes: tuple[ScopeIds, ...],
) -> tuple[ClassifiedOverride, ...]:
    """Classify relevant rows by the resolver's own precedence decision.

    A live row selected for at least one supplied complete subject is active. A
    live row that matches but never wins is shadowed; an elapsed row is expired.
    Deactivated rows are historical register entries and deliberately omitted
    from subject pages.
    """
    rows = await _candidates(tx, rule_domains, scopes, include_expired=True)
    now = cast(datetime, await tx.scalar(sa.select(sa.func.now())))
    return _classify(rows, rule_domains, scopes, now)


async def classified_by_scope[ScopeKey](
    tx: OverrideConnection,
    rule_domains: tuple[RuleDomain, ...],
    scopes: Mapping[ScopeKey, ScopeIds],
) -> dict[ScopeKey, tuple[ClassifiedOverride, ...]]:
    """Classify each complete subject independently with one candidate query."""
    rows = await _candidates(
        tx, rule_domains, tuple(scopes.values()), include_expired=True
    )
    now = cast(datetime, await tx.scalar(sa.select(sa.func.now())))
    return {
        key: _classify(rows, rule_domains, (scope_ids,), now)
        for key, scope_ids in scopes.items()
    }
