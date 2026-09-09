"""Per-domain integration proofs for INT-2's scoped overrides.

M2 built the resolver and M5 built the gates that read it, and both have unit
tests.  What neither proves is that a real command, driven end to end through
the real executor, is actually bypassed -- and that is the only claim INT-2
makes.  Every test here therefore runs a production command against a seeded
world, twice: once with no override, once with one.

The suite is parametrized over ``RuleDomain`` itself rather than over a list
written here, so a domain added to the enum without a world fails immediately
with a message saying which world to write.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.db import create_engine
from app.core.errors import BLOCKED_BY_OVERRIDE
from app.core.executor import Executor
from app.domain.shared import RuleDomain
from tests.overrides.conftest import (
    WORLD_BUILDERS,
    DomainWorld,
    Person,
    build_test_executor,
    grant,
    seed_admin,
)

pytestmark = pytest.mark.asyncio

DOMAINS = list(RuleDomain)
IDS = [item.value for item in DOMAINS]


def _builder(
    domain: RuleDomain,
) -> Callable[[AsyncConnection, Executor], Awaitable[DomainWorld]]:
    builder = WORLD_BUILDERS.get(domain)
    assert builder is not None, (
        f"Rule domain {domain.value!r} has no world in tests/overrides/conftest.py. "
        "Add one: a domain nothing drives end to end is a domain whose bypass "
        "has never been proven against a real command."
    )
    return builder


def _write_engine():  # noqa: ANN202 - compact test helper
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


async def _world(domain: RuleDomain) -> tuple[DomainWorld, Person]:
    """Build the domain's world plus the administrator who grants in it."""
    executor, _engine = build_test_executor()
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(
                connection, email=f"admin-{domain.value}-{os.urandom(4).hex()}@example.edu"
            )
            world = await _builder(domain)(connection, executor)
    finally:
        await engine.dispose()
    return world, admin


async def _grant(
    world: DomainWorld,
    admin: Person,
    *,
    scope: str,
    domain: RuleDomain | None = None,
    allow: bool = True,
    is_active: bool = True,
    expires_at: datetime | None = None,
) -> UUID:
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            targets = world.scope_kwargs(scope)
            return await grant(
                connection,
                domain=domain or world.domain,
                granted_by=admin.user_id,
                allow=allow,
                is_active=is_active,
                expires_at=expires_at,
                cycle_id=targets.get("cycle_id"),
                job_id=targets.get("job_id"),
                enrollment_id=targets.get("enrollment_id"),
                application_id=targets.get("application_id"),
            )
    finally:
        await engine.dispose()


async def _grant_neighbours(world: DomainWorld, admin: Person) -> None:
    """Grant the other domains this world cannot separate from its own."""
    for neighbour in world.also_grant:
        await _grant(world, admin, scope=world.ladder[-1], domain=neighbour)


@pytest.mark.parametrize("domain", DOMAINS, ids=IDS)
async def test_INT2_gate_fails_without_the_override_and_passes_with_it(
    domain: RuleDomain, clean_overrides: None
) -> None:
    del clean_overrides
    world, admin = await _world(domain)

    refused = await world.run()
    assert not refused.accepted
    assert world.expected_code in refused.codes

    await _grant(world, admin, scope=world.ladder[0])
    if world.also_grant:
        # This world cannot make the domain fail alone, so the intermediate run
        # is the sharper assertion: this domain's reason is gone and the
        # neighbouring one still stands.  An override is a bypass of one domain,
        # never a general amnesty.
        partial = await world.run()
        assert not partial.accepted
        assert world.expected_code not in partial.codes
        for residual in world.residual_codes:
            assert residual in partial.codes
        await _grant_neighbours(world, admin)

    allowed = await world.run()
    assert allowed.accepted, (
        f"{domain.value} was still refused with an override granted: {allowed.codes}"
    )


@pytest.mark.parametrize("domain", DOMAINS, ids=IDS)
async def test_INT2_an_expired_override_is_inert(
    domain: RuleDomain, clean_overrides: None
) -> None:
    del clean_overrides
    world, admin = await _world(domain)
    await _grant(
        world,
        admin,
        scope=world.ladder[0],
        expires_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    await _grant_neighbours(world, admin)

    attempt = await world.run()
    assert not attempt.accepted
    assert world.expected_code in attempt.codes


@pytest.mark.parametrize("domain", DOMAINS, ids=IDS)
async def test_INT2_a_deactivated_override_is_inert(
    domain: RuleDomain, clean_overrides: None
) -> None:
    del clean_overrides
    world, admin = await _world(domain)
    await _grant(world, admin, scope=world.ladder[0], is_active=False)
    await _grant_neighbours(world, admin)

    attempt = await world.run()
    assert not attempt.accepted
    assert world.expected_code in attempt.codes


@pytest.mark.parametrize("domain", DOMAINS, ids=IDS)
async def test_INT2_specificity_resolves_application_enrollment_job_cycle(
    domain: RuleDomain, clean_overrides: None
) -> None:
    """The most specific applicable grant is the one the decision credits.

    Every scope grants the same permission, so the command succeeds each time
    and the only thing that changes is *which id the event names* -- which is
    exactly the question specificity answers.  The world is rebuilt between
    steps because the commands under test move state that cannot move twice,
    and each rebuild grants one fewer scope, promoting the next one down.
    """
    del clean_overrides
    for index, scope in enumerate(world_ladder := _ladder(domain)):
        world, admin = await _world(domain)
        winner: UUID | None = None
        for candidate in world_ladder[index:]:
            granted = await _grant(world, admin, scope=candidate)
            if winner is None:
                winner = granted
        await _grant_neighbours(world, admin)

        attempt = await world.run()
        assert attempt.accepted, (
            f"{domain.value} was refused with {scope}-scoped grant: {attempt.codes}"
        )
        assert winner in attempt.applied_override_ids, (
            f"{domain.value} credited {attempt.applied_override_ids} rather than the "
            f"{scope}-scoped override {winner}"
        )


def _ladder(domain: RuleDomain) -> tuple[str, ...]:
    """The scopes this domain's command can resolve, most specific first."""
    return {
        RuleDomain.ELIGIBILITY: (
            "job+enrollment",
            "cycle+enrollment",
            "enrollment",
            "job",
            "cycle",
        ),
        RuleDomain.APPLICATION_DEADLINE: (
            "job+enrollment",
            "cycle+enrollment",
            "enrollment",
            "job",
            "cycle",
        ),
        RuleDomain.CYCLE_REGISTRATION_WINDOW: (
            "cycle+enrollment",
            "enrollment",
            "cycle",
        ),
        RuleDomain.CYCLE_JOIN_RULE: (
            "cycle+enrollment",
            "enrollment",
            "cycle",
        ),
    }.get(
        domain,
        (
            "application",
            "job+enrollment",
            "cycle+enrollment",
            "enrollment",
            "job",
            "cycle",
        ),
    )


@pytest.mark.parametrize("domain", DOMAINS, ids=IDS)
async def test_INT2_equal_specificity_deny_beats_allow(
    domain: RuleDomain, clean_overrides: None
) -> None:
    """the design review section 4.14: at equal specificity, ``allow=false`` wins.

    The denial is not merely "no bypass": it forces the domain to fail with
    ``blocked_by_override`` even where the underlying gate would have passed,
    which is what makes a standing block a usable instrument rather than the
    absence of a grant.
    """
    del clean_overrides
    world, admin = await _world(domain)
    scope = world.ladder[0]
    await _grant(world, admin, scope=scope, allow=True)
    await _grant(world, admin, scope=scope, allow=False)
    await _grant_neighbours(world, admin)

    attempt = await world.run()
    assert not attempt.accepted
    assert BLOCKED_BY_OVERRIDE in attempt.codes


@pytest.mark.parametrize("domain", DOMAINS, ids=IDS)
async def test_INT2_the_applied_override_id_lands_in_the_event_payload(
    domain: RuleDomain, clean_overrides: None
) -> None:
    """INT-2: "every influenced decision stamps the override into its event"."""
    del clean_overrides
    world, admin = await _world(domain)
    override_id = await _grant(world, admin, scope=world.ladder[0])
    await _grant_neighbours(world, admin)

    attempt = await world.run()
    assert attempt.accepted
    assert override_id in attempt.applied_override_ids


async def test_INT2_the_unbypassable_gates_have_no_rule_domain() -> None:
    """Cycle-active, membership, job-open, duplicate and penalty stay unreachable.

    the design review section 4.14 and Behavior INT-2 both say a bypass for these is not
    merely disallowed but unrepresentable, and this is where that is true: a
    domain absent from the enum cannot be stored in a column whose type is the
    enum, so no override row can ever name one.
    """
    values = {domain.value for domain in RuleDomain}
    assert values == {
        "eligibility",
        "application_deadline",
        "edit_window",
        "withdraw_window",
        "outcome_gate",
        "offer_cap",
        "offer_deadline",
        "cycle_registration_window",
        "cycle_join_rule",
    }
    for forbidden in (
        "cycle_active",
        "membership",
        "job_open",
        "duplicate_application",
        "penalty",
    ):
        assert forbidden not in values

    engine = _write_engine()
    try:
        async with engine.connect() as connection:
            stored = set(
                (
                    await connection.scalars(
                        sa.text("SELECT unnest(enum_range(NULL::rule_domain_t))::text")
                    )
                ).all()
            )
    finally:
        await engine.dispose()
    assert stored == values
