"""The admin override register and its the design review section 4.22 equivalence pin."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID

import pytest

from app.core.db import create_engine
from app.core.errors import DomainRejection
from app.core.plan import ActorContext, Preview
from app.domain.shared import RuleDomain
from app.modules.overrides.commands import DeactivateOverrideInput
from app.modules.overrides.queries import admin_overrides
from tests.cycles.conftest import seed_admin, seed_cycle, seed_job, seed_person
from tests.overrides.conftest import build_test_executor, grant

pytestmark = pytest.mark.asyncio


def _write_engine():  # noqa: ANN202 - compact test helper
    return create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])


def _read_engine():  # noqa: ANN202 - compact test helper
    return create_engine(os.environ["TEST_DATABASE_URL"])


def _row(body: dict[str, object], override_id: UUID) -> dict[str, object]:
    rows = cast("list[dict[str, object]]", body["overrides"])
    match = next((row for row in rows if row["id"] == str(override_id)), None)
    assert match is not None, f"{override_id} is missing from the register"
    return match


async def _register(**filters: object) -> dict[str, object]:
    engine = _read_engine()
    try:
        return await admin_overrides(engine, **filters)  # type: ignore[arg-type]
    finally:
        await engine.dispose()


async def _world() -> dict[str, UUID]:
    engine = _write_engine()
    try:
        async with engine.begin() as connection:
            admin = await seed_admin(connection)
            student = await seed_person(connection, email="drill@example.edu")
            cycle_id = await seed_cycle(connection, name="Placement 2026")
            job_id = await seed_job(connection, cycle_id=cycle_id, title="SRE")
            active = await grant(
                connection,
                domain=RuleDomain.APPLICATION_DEADLINE,
                granted_by=admin.user_id,
                cycle_id=cycle_id,
            )
            expired = await grant(
                connection,
                domain=RuleDomain.OFFER_DEADLINE,
                granted_by=admin.user_id,
                job_id=job_id,
                expires_at=datetime.now(UTC) - timedelta(days=1),
            )
            deactivated = await grant(
                connection,
                domain=RuleDomain.OFFER_CAP,
                granted_by=admin.user_id,
                enrollment_id=student.enrollment_id,
                is_active=False,
            )
            combined = await grant(
                connection,
                domain=RuleDomain.ELIGIBILITY,
                granted_by=admin.user_id,
                job_id=job_id,
                enrollment_id=student.enrollment_id,
            )
    finally:
        await engine.dispose()
    return {
        "admin": admin.user_id,
        "cycle": cycle_id,
        "job": job_id,
        "enrollment": student.enrollment_id,
        "active": active,
        "expired": expired,
        "deactivated": deactivated,
        "combined": combined,
    }


async def test_INT2_the_register_names_each_scope_and_its_live_state(
    clean_overrides: None,
) -> None:
    """"Listed, filterable, one-click deactivation" -- starting with listed."""
    del clean_overrides
    ids = await _world()
    body = await _register()

    assert _row(body, ids["active"])["state"] == "active"
    # is_active is still true on the expired row; the resolver ignores it
    # anyway, so a screen that called it live would be describing a grant that
    # does nothing.
    expired = _row(body, ids["expired"])
    assert expired["state"] == "expired" and expired["is_active"] is True
    assert _row(body, ids["deactivated"])["state"] == "deactivated"

    assert _row(body, ids["active"])["scope"] == "cycle"
    assert _row(body, ids["expired"])["scope"] == "job"
    assert _row(body, ids["deactivated"])["scope"] == "enrollment"
    assert _row(body, ids["combined"])["scope"] == "job+enrollment"
    assert "SRE" in str(_row(body, ids["combined"])["subject_label"])
    assert _row(body, ids["expired"])["subject_label"] == "SRE"
    assert cast("dict[str, object]", body["counts"]) == {
        "active": 2,
        "expired": 1,
        "deactivated": 1,
    }


async def test_INT2_the_register_filters_by_domain_scope_cycle_and_state(
    clean_overrides: None,
) -> None:
    del clean_overrides
    ids = await _world()

    by_domain = await _register(rule_domain=RuleDomain.OFFER_CAP.value)
    assert [row["id"] for row in cast("list[dict[str, object]]", by_domain["overrides"])] == [
        str(ids["deactivated"])
    ]

    by_scope = await _register(scope="job")
    assert [row["id"] for row in cast("list[dict[str, object]]", by_scope["overrides"])] == [
        str(ids["expired"])
    ]
    by_combination = await _register(scope="job+enrollment")
    assert [
        row["id"]
        for row in cast("list[dict[str, object]]", by_combination["overrides"])
    ] == [str(ids["combined"])]

    by_state = await _register(state="active")
    assert {
        row["id"]
        for row in cast("list[dict[str, object]]", by_state["overrides"])
    } == {str(ids["active"]), str(ids["combined"])}

    # The enrollment-scoped grant belongs to no cycle, so a cycle filter must
    # not sweep it in beside the two that do.
    by_cycle = await _register(cycle_id=ids["cycle"])
    assert {
        row["id"] for row in cast("list[dict[str, object]]", by_cycle["overrides"])
    } == {str(ids["active"]), str(ids["expired"]), str(ids["combined"])}


async def test_INT2_what_the_register_offers_is_what_deactivate_allows(
    clean_overrides: None,
) -> None:
    """Section 4.22: the button's verdict is the command's verdict, in every state.

    Asserting only the allowed case would not be a pin -- the failure this
    exists to catch is a control that never appears, or one that appears and is
    then refused.
    """
    del clean_overrides
    ids = await _world()
    executor, _engine = build_test_executor()
    actor = ActorContext(
        principal_id=str(ids["admin"]),
        user_id=ids["admin"],
        role="admin",
        session_id=ids["admin"],
    )

    body = await _register()
    for key in ("active", "expired", "deactivated", "combined"):
        override_id = ids[key]
        offered = cast(
            "dict[str, object]",
            cast("dict[str, object]", _row(body, override_id)["actions"])["deactivate"],
        )
        try:
            preview = await executor.run(
                "deactivate_override",
                DeactivateOverrideInput(override_id=override_id),
                actor,
                dry_run=True,
            )
            allowed = isinstance(preview, Preview)
            code: str | None = None
        except DomainRejection as rejection:
            allowed = False
            code = rejection.rejection.reasons[0].code

        assert offered["allowed"] is allowed, (
            f"the register offers {offered['allowed']} for the {key} override while "
            f"the command answers {allowed}"
        )
        assert offered["reason"] == code
