"""Application registry and executor assembly."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.authz import Authorizer
from app.core.executor import Executor
from app.core.harness import register_harness
from app.core.registry import Registry
from app.modules.admin.commands import register_admin_commands
from app.modules.admin.screens import register_admin_screens
from app.modules.analytics.exports import register_export_commands
from app.modules.analytics.screens import register_analytics_screens
from app.modules.applications.attendance import register_attendance_commands
from app.modules.applications.commands import register_application_commands
from app.modules.applications.finalization import register_finalization_commands
from app.modules.applications.lifecycle import register_application_lifecycle_commands
from app.modules.applications.rounds import register_round_commands
from app.modules.applications.screens import register_application_screens
from app.modules.applications.venues import register_venue_commands
from app.modules.companies.commands import register_company_commands
from app.modules.companies.screens import register_company_screens
from app.modules.cycles.commands import register_cycle_commands
from app.modules.cycles.memberships import (
    register_membership_commands,
    register_membership_exit_commands,
)
from app.modules.cycles.screens import register_cycle_screens
from app.modules.discipline.commands import register_discipline_commands
from app.modules.discipline.screens import register_discipline_screens
from app.modules.identity.admin_commands import register_identity_admin_commands
from app.modules.identity.commands import register_identity_commands
from app.modules.identity.screens import register_identity_screens
from app.modules.interventions.commands import register_intervention_commands
from app.modules.interventions.screens import register_intervention_screens
from app.modules.jobs.builder import register_job_builder_commands
from app.modules.jobs.cancel import register_job_cancellation_commands
from app.modules.jobs.commands import register_job_commands
from app.modules.jobs.eligibility import register_job_eligibility_commands
from app.modules.jobs.screens import register_job_screens
from app.modules.notifications.commands import register_notification_commands
from app.modules.notifications.reminders import register_reminder_commands
from app.modules.notifications.screens import register_notification_screens
from app.modules.offers.commands import register_offer_commands
from app.modules.offers.expiry import register_expiry_commands
from app.modules.offers.external import register_external_offer_commands
from app.modules.offers.screens import register_offer_screens
from app.modules.offers.termination import register_termination_commands
from app.modules.overrides.commands import register_override_commands
from app.modules.overrides.screens import register_override_screens
from app.modules.overrides.service import applicable
from app.modules.profiles.bulk import register_bulk_commands
from app.modules.profiles.commands import register_profile_commands
from app.modules.profiles.screens import register_profile_screens
from app.modules.profiles.staged import (
    register_staged_commands,
    register_staged_login_hook,
)
from app.modules.taxonomies.commands import register_taxonomy_commands
from app.modules.taxonomies.screens import register_taxonomy_screens
from app.settings import Settings


def build_registry(
    *, settings: Settings | None = None, enable_test_harness: bool = False
) -> Registry:
    registry = Registry()
    register_staged_login_hook()
    register_identity_commands(registry, settings=settings or Settings.from_env())
    register_identity_admin_commands(registry)
    register_identity_screens(registry)
    register_notification_commands(registry)
    register_reminder_commands(registry)
    register_notification_screens(registry)
    register_company_commands(registry)
    register_company_screens(registry)
    register_cycle_commands(registry)
    register_membership_commands(registry)
    register_membership_exit_commands(registry)
    register_cycle_screens(registry)
    register_job_commands(registry)
    register_job_eligibility_commands(registry)
    register_job_builder_commands(registry)
    register_job_cancellation_commands(registry)
    register_job_screens(registry)
    register_application_commands(registry)
    register_application_lifecycle_commands(registry)
    register_round_commands(registry)
    register_attendance_commands(registry)
    register_venue_commands(registry)
    register_finalization_commands(registry)
    register_offer_commands(registry)
    register_expiry_commands(registry)
    register_external_offer_commands(registry)
    register_termination_commands(registry)
    register_offer_screens(registry)
    register_discipline_commands(registry)
    register_discipline_screens(registry)
    register_override_commands(registry)
    register_intervention_commands(registry)
    register_admin_commands(registry)
    register_override_screens(registry)
    register_intervention_screens(registry)
    register_admin_screens(registry)
    register_export_commands(registry)
    register_analytics_screens(registry)
    register_application_screens(registry)
    register_profile_commands(registry)
    register_bulk_commands(registry)
    register_staged_commands(registry)
    register_profile_screens(registry)
    register_taxonomy_commands(registry)
    register_taxonomy_screens(registry)
    if enable_test_harness:
        register_harness(registry)
    return registry


def build_executor(
    registry: Registry, engine: AsyncEngine, *, authorizer: Authorizer | None = None
) -> Executor:
    factory = async_sessionmaker[AsyncSession](
        engine, expire_on_commit=False, autobegin=False
    )
    return Executor(
        registry=registry,
        session_factory=factory,
        authorizer=authorizer or Authorizer(),
        override_resolver=applicable,
    )
