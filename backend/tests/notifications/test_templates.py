"""Template catalog, resolution, and rendering gates for Behavior NTF."""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa

from app.core.db import create_engine
from app.core.executor import Executor
from app.core.plan import ActorContext
from app.modules.notifications.catalog import EVENT_KEYS
from app.modules.notifications.commands import UpdateTemplateInput
from app.modules.notifications.queries import resolve_template
from app.modules.notifications.render import render_text

EXPECTED_NOTIFICATION_EVENT_KEYS = {
    "application_submitted",
    "advanced",
    "rejected",
    "absent_marked",
    "offer_extended",
    "offer_accepted",
    "declined_confirm",
    "auto_declined",
    "auto_withdrawn",
    "offer_terminated",
    "offer_expired",
    "external_recorded",
    "external_updated",
    "strike_added",
    "strike_revoked",
    "penalty_added",
    "penalty_revoked",
    "venue_timing",
    "process_changed",
    "deadline_changed",
    "job_cancelled",
    "membership_pending",
    "membership_approved",
    "membership_rejected",
    "membership_removed",
    "membership_restored",
    "coordinator_assigned",
    "coordinator_removed",
    "deadline_reminder",
    "round_reminder",
    "reinstated",
}
ADMIN = UUID("00000000-0000-0000-0000-000000001301")
ADMIN_ACTOR = ActorContext(
    principal_id=str(ADMIN),
    user_id=ADMIN,
    role="admin",
    session_id=UUID("00000000-0000-0000-0000-000000001302"),
)


def _literal_event_keys(node: ast.expr | None) -> set[str]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return {node.value}
    if isinstance(node, ast.IfExp):
        return _literal_event_keys(node.body) | _literal_event_keys(node.orelse)
    if isinstance(node, (ast.List, ast.Set, ast.Tuple)):
        return set().union(*(_literal_event_keys(item) for item in node.elts), set())
    return set()


def _emitted_notification_event_keys() -> set[str]:
    """Statically collect event keys that production notification intents can emit."""
    app_root = Path(__file__).parents[2] / "app"
    emitted: set[str] = set()
    for path in app_root.rglob("*.py"):
        if path.name == "catalog.py" and path.parent.name == "notifications":
            continue
        tree = ast.parse(path.read_text())
        positional_event_key: dict[str, int] = {}
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            positional = [*node.args.posonlyargs, *node.args.args]
            for index, argument in enumerate(positional):
                if argument.arg == "event_key":
                    positional_event_key[node.name] = index
            default_offset = len(positional) - len(node.args.defaults)
            for index, default in enumerate(node.args.defaults, default_offset):
                if positional[index].arg == "event_key":
                    emitted.update(_literal_event_keys(default))
            for argument, default in zip(
                node.args.kwonlyargs, node.args.kw_defaults, strict=True
            ):
                if argument.arg == "event_key":
                    emitted.update(_literal_event_keys(default))

        for node in ast.walk(tree):
            values: list[ast.expr | None] = []
            if isinstance(node, ast.Dict):
                values.extend(
                    value
                    for key, value in zip(node.keys, node.values, strict=True)
                    if isinstance(key, ast.Constant) and key.value == "event_key"
                )
            elif isinstance(node, ast.Call):
                values.extend(
                    keyword.value for keyword in node.keywords if keyword.arg == "event_key"
                )
                if isinstance(node.func, ast.Name):
                    index = positional_event_key.get(node.func.id)
                    if index is not None and index < len(node.args):
                        values.append(node.args[index])
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(
                    isinstance(target, ast.Name) and target.id == "event_key"
                    for target in targets
                ):
                    values.append(node.value)
            for value in values:
                emitted.update(_literal_event_keys(value))
    return emitted


def test_NTF_every_production_emitter_has_an_exact_catalog_entry() -> None:
    """An emitter added without a seeded template must fail at build time."""
    # 28 in LLD section 13, plus deadline_changed and declined_confirm
    # (the design review section 4.27) and reinstated (section 4.28).
    assert len(EXPECTED_NOTIFICATION_EVENT_KEYS) == 31
    assert _emitted_notification_event_keys() == EXPECTED_NOTIFICATION_EVENT_KEYS


@pytest.mark.asyncio
async def test_NTF_seeded_template_set_exactly_equals_effective_catalog() -> None:
    """A catalog key without a migration row must fail this build gate."""
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            seeded = set(
                (
                    await connection.execute(
                        sa.text(
                            "SELECT event_key FROM notification_templates WHERE cycle_id IS NULL"
                        )
                    )
                ).scalars()
            )
    finally:
        await engine.dispose()
    assert set(EVENT_KEYS) == EXPECTED_NOTIFICATION_EVENT_KEYS
    assert seeded == EXPECTED_NOTIFICATION_EVENT_KEYS


@pytest.mark.asyncio
async def test_NTF_template_resolution_is_cycle_override_then_global(
    notification_executor: Executor,
) -> None:
    cycle_id = uuid4()
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "INSERT INTO users (id, email, full_name, role) "
                    "VALUES (:id, 'template-admin@example.edu', 'Template Admin', 'admin')"
                ),
                {"id": ADMIN},
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO cycles (id, name, kind, is_active) "
                    "VALUES (:id, 'Override Cycle', 'placement', true)"
                ),
                {"id": cycle_id},
            )
    finally:
        await engine.dispose()

    global_engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with global_engine.connect() as connection:
            global_template = await resolve_template(connection, "offer_extended", cycle_id)
        assert global_template is not None
        assert global_template.cycle_id is None

        await notification_executor.run(
            "update_template",
            UpdateTemplateInput(
                event_key="offer_extended",
                cycle_id=cycle_id,
                subject="Cycle offer: {job}",
                body="Cycle copy for {student}",
                enabled=False,
            ),
            ADMIN_ACTOR,
        )
        async with global_engine.connect() as connection:
            resolved = await resolve_template(connection, "offer_extended", cycle_id)
            other = await resolve_template(connection, "offer_extended", uuid4())
    finally:
        await global_engine.dispose()

    assert resolved is not None
    assert resolved.cycle_id == cycle_id
    assert resolved.subject == "Cycle offer: {job}"
    # A disabled override is itself the per-cycle toggle; it does not fall back
    # to an enabled global row and accidentally send the event.
    assert resolved.enabled is False
    assert other is not None and other.cycle_id is None and other.enabled is True


def test_NTF_missing_render_variable_is_blank_warns_and_never_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        rendered = render_text(
            "Hello {student}; venue: {venue}; time: {time}",
            {"student": "Asha", "time": None},
            event_key="round_reminder",
            part="body",
        )
    assert rendered.text == "Hello Asha; venue: ; time: "
    assert rendered.missing == ("venue",)
    assert "rendering it blank" in caplog.text


@pytest.mark.asyncio
async def test_NTF_offer_extended_default_renders_the_student_copy_fully() -> None:
    engine = create_engine(os.environ["TEST_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            template = await resolve_template(connection, "offer_extended", None)
    finally:
        await engine.dispose()
    assert template is not None
    context = {
        "student": "Asha Mehta",
        "job": "Backend Engineer",
        "company": "Northwind Systems",
        "deadline": "18 September 2026, 5:00 PM IST",
    }
    subject = render_text(
        template.subject, context, event_key="offer_extended", part="subject"
    ).text
    body = render_text(template.body, context, event_key="offer_extended", part="body").text
    assert subject == "Offer extended: Backend Engineer at Northwind Systems"
    assert "Dear Asha Mehta" in body
    assert "Response deadline: 18 September 2026, 5:00 PM IST" in body
    assert "{" not in subject + body
