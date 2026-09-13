"""0018 preserves stored rule identity while versioning its evaluator contract."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection

from app.core.db import create_engine

pytestmark = pytest.mark.asyncio


def migration() -> ModuleType:
    path = Path(__file__).parents[2] / "alembic/versions/0018_rule_semantics.py"
    spec = importlib.util.spec_from_file_location("rule_semantics_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migration(connection: Connection, direction: str) -> None:
    with Operations.context(MigrationContext.configure(connection)):
        getattr(migration(), direction)()


async def test_ELG2_existing_rules_stay_v1_and_new_rules_default_to_v2() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    cycle_id, policy_id, company_id, old_job_id, new_job_id = (
        uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    )
    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.run_sync(run_migration, "downgrade")
                await connection.execute(
                    sa.text(
                        "INSERT INTO cycles (id, name, kind) "
                        "VALUES (:id, :name, 'placement')"
                    ),
                    {"id": cycle_id, "name": f"Rule migration {cycle_id}"},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO companies (id, name) VALUES (:id, :name)"
                    ),
                    {"id": company_id, "name": f"Rule migration {company_id}"},
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO cycle_policies "
                        "(id, cycle_id, membership_requires_approval, join_rule, "
                        "max_accepted_offers, penalty_blocks_applications, "
                        "allow_withdrawal_after_deadline, allow_edit_after_deadline, "
                        "strike_on_absence) VALUES "
                        "(:id, :cycle, true, CAST(:rule AS jsonb), 1, true, false, "
                        "false, true)"
                    ),
                    {
                        "id": policy_id,
                        "cycle": cycle_id,
                        "rule": '{"not":{"field":"cpi","op":"gte","value":8}}',
                    },
                )
                await connection.execute(
                    sa.text(
                        "INSERT INTO jobs "
                        "(id, cycle_id, company_id, outcome, title, description, "
                        "eligibility_rule) VALUES "
                        "(:id, :cycle, :company, 'placement', 'Old', '', "
                        "CAST(:rule AS jsonb))"
                    ),
                    {
                        "id": old_job_id,
                        "cycle": cycle_id,
                        "company": company_id,
                        "rule": '{"field":"program_id","op":"eq",'
                        f'"value":"{uuid4()}"}}',
                    },
                )

                await connection.run_sync(run_migration, "upgrade")
                versions = (
                    await connection.execute(
                        sa.text(
                            "SELECT j.eligibility_rule_version, cp.join_rule_version "
                            "FROM jobs j JOIN cycle_policies cp "
                            "ON cp.cycle_id = j.cycle_id WHERE j.id = :id"
                        ),
                        {"id": old_job_id},
                    )
                ).one()
                assert tuple(versions) == (1, 1)

                await connection.execute(
                    sa.text(
                        "INSERT INTO jobs "
                        "(id, cycle_id, company_id, outcome, title, description) "
                        "VALUES (:id, :cycle, :company, 'placement', 'New', '')"
                    ),
                    {"id": new_job_id, "cycle": cycle_id, "company": company_id},
                )
                assert await connection.scalar(
                    sa.text(
                        "SELECT eligibility_rule_version FROM jobs WHERE id = :id"
                    ),
                    {"id": new_job_id},
                ) == 2
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()
