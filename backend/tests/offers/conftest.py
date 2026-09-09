"""Shared database reset and factories for the M12 offer suites."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from tests.applications.conftest import clean_applications  # noqa: F401
from tests.cycles.conftest import (  # noqa: F401
    build_test_executor,
    seed_admin,
    seed_application,
    seed_complete_profile,
    seed_cycle,
    seed_job,
    seed_membership,
    seed_person,
    seed_taxonomy,
)


async def seed_portal_offer(
    connection: AsyncConnection,
    *,
    application_id: UUID,
    response: str | None = None,
    deadline: datetime | None = None,
    extended_at: datetime | None = None,
    terminated: bool = False,
) -> UUID:
    offer_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO offers (id, application_id, extended_at, deadline_at, "
            "response, responded_at, terminated_at, termination_kind, "
            "termination_reason) VALUES "
            "(:id, :application_id, :extended_at, :deadline, "
            "CAST(:response AS offer_response_t), "
            "CASE WHEN :response IS NULL THEN NULL ELSE now() END, "
            "CASE WHEN :terminated THEN now() ELSE NULL END, "
            "CASE WHEN :terminated THEN 'admin_correction'::termination_kind_t "
            "ELSE NULL END, "
            "CASE WHEN :terminated THEN 'Test correction' ELSE NULL END)"
        ),
        {
            "id": offer_id,
            "application_id": application_id,
            "extended_at": extended_at or datetime.now(UTC),
            "deadline": deadline,
            "response": response,
            "terminated": terminated,
        },
    )
    return offer_id


async def seed_external_offer(
    connection: AsyncConnection,
    *,
    enrollment_id: UUID,
    company_id: UUID,
    created_by: UUID,
    outcome: str = "placement",
    source: str = "off_campus",
    status: str = "offered",
    attached_cycle_id: UUID | None = None,
    source_application_id: UUID | None = None,
    ctc_lpa: Decimal | None = None,
    stipend_month: Decimal | None = None,
    offered_on: date | None = None,
) -> UUID:
    external_offer_id = uuid4()
    await connection.execute(
        sa.text(
            "INSERT INTO external_offers (id, enrollment_id, company_id, outcome, "
            "source, ctc_lpa, stipend_month, status, offered_on, responded_on, "
            "source_application_id, attached_cycle_id, created_by) VALUES "
            "(:id, :enrollment_id, :company_id, CAST(:outcome AS outcome_t), "
            "CAST(:source AS external_source_t), :ctc_lpa, :stipend_month, "
            "CAST(:status AS external_status_t), :offered_on, "
            "CASE WHEN :status = 'offered' THEN NULL ELSE CURRENT_DATE END, "
            ":source_application_id, :attached_cycle_id, :created_by)"
        ),
        {
            "id": external_offer_id,
            "enrollment_id": enrollment_id,
            "company_id": company_id,
            "outcome": outcome,
            "source": source,
            "ctc_lpa": ctc_lpa,
            "stipend_month": stipend_month,
            "status": status,
            "offered_on": offered_on,
            "source_application_id": source_application_id,
            "attached_cycle_id": attached_cycle_id,
            "created_by": created_by,
        },
    )
    return external_offer_id


async def set_offer_deadline(
    connection: AsyncConnection,
    job_id: UUID,
    *,
    days: int = 60,
) -> datetime:
    deadline = datetime.now(UTC) + timedelta(days=days)
    await connection.execute(
        sa.text("UPDATE jobs SET offer_acceptance_deadline = :value WHERE id = :id"),
        {"id": job_id, "value": deadline},
    )
    return deadline
