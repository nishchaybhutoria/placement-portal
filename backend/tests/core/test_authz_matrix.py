"""Generated authorization matrix for Behavior IDN-3."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest

from app.bootstrap import build_registry
from app.core.authz import Authorizer
from app.core.errors import AuthorizationDenied
from app.core.plan import ActorContext
from app.settings import Settings

USER = UUID("00000000-0000-0000-0000-000000000401")
SESSION = UUID("00000000-0000-0000-0000-000000000402")
ENROLLMENT = UUID("00000000-0000-0000-0000-000000000403")
MEMBERSHIP = UUID("00000000-0000-0000-0000-000000000412")
RESUME_DEFAULT = UUID("00000000-0000-0000-0000-000000000413")
CYCLE_A = UUID("00000000-0000-0000-0000-000000000404")
CYCLE_B = UUID("00000000-0000-0000-0000-000000000405")
RESUME = UUID("00000000-0000-0000-0000-000000000406")
STAGED_ROW = UUID("00000000-0000-0000-0000-000000000407")
DRIVE_URL = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"
COMPANY = UUID("00000000-0000-0000-0000-000000000408")
CYCLE_ANY = UUID("00000000-0000-0000-0000-000000000411")
OTHER_COMPANY = UUID("00000000-0000-0000-0000-000000000409")
CONTACT = UUID("00000000-0000-0000-0000-000000000410")
JOB = UUID("00000000-0000-0000-0000-000000000414")
APPLICATION = UUID("00000000-0000-0000-0000-000000000415")
ROUND = UUID("00000000-0000-0000-0000-000000000416")
ENROLLMENT = UUID("00000000-0000-0000-0000-000000000417")
STRIKE = UUID("00000000-0000-0000-0000-000000000418")
PENALTY = UUID("00000000-0000-0000-0000-000000000419")
OFFER = UUID("00000000-0000-0000-0000-000000000420")
NOTIFICATION = UUID("00000000-0000-0000-0000-000000000421")
OVERRIDE = UUID("00000000-0000-0000-0000-000000000422")
FINDING = UUID("00000000-0000-0000-0000-000000000423")
STAFF = frozenset({"coordinator_a", "coordinator_b", "admin"})


@dataclass(frozen=True)
class MatrixFixture:
    input: dict[str, object]
    allowed: frozenset[str]


FIXTURES = {
    "issue_oauth_state": MatrixFixture({}, frozenset()),
    "consume_oauth_state": MatrixFixture({}, frozenset()),
    "google_login": MatrixFixture(
        {"email": "student@example.edu", "full_name": "Student"}, frozenset()
    ),
    "update_template": MatrixFixture(
        {
            "event_key": "offer_extended",
            "subject": "Offer: {job}",
            "body": "Hello {student}",
            "enabled": True,
        },
        frozenset({"admin"}),
    ),
    "resend_notification": MatrixFixture(
        {"notification_id": str(NOTIFICATION)}, STAFF
    ),
    "deliver_notification": MatrixFixture(
        {
            "notification_id": str(NOTIFICATION),
            "event_key": "offer_extended",
            "recipient": "student@example.edu",
            "context": {},
        },
        frozenset(),
    ),
    "record_notification_attempt": MatrixFixture(
        {
            "notification_id": str(NOTIFICATION),
            "delivered": False,
            "error": "SES unavailable",
        },
        frozenset(),
    ),
    "send_deadline_reminders": MatrixFixture({}, frozenset()),
    "send_round_reminders": MatrixFixture({}, frozenset()),
    "enforce_offer_expiry": MatrixFixture(
        {
            "offer_id": str(OFFER),
            "scheduled_deadline": "2027-01-01T00:00:00Z",
        },
        frozenset(),
    ),
    "logout": MatrixFixture({}, frozenset({"student", "coordinator_a", "coordinator_b", "admin"})),
    "start_new_enrollment": MatrixFixture(
        {"user_id": str(USER)}, frozenset({"admin"})
    ),
    "set_user_role": MatrixFixture(
        {"user_id": str(USER), "role": "student"}, frozenset({"admin"})
    ),
    "deactivate_user": MatrixFixture(
        {"user_id": str(USER)}, frozenset({"admin"})
    ),
    "declare_profile": MatrixFixture(
        {"enrollment_id": str(ENROLLMENT), "fields": {}},
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "update_student_fields": MatrixFixture(
        {"enrollment_id": str(ENROLLMENT), "fields": {}},
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "admin_update_profile": MatrixFixture(
        {"enrollment_id": str(ENROLLMENT), "fields": {}}, frozenset({"admin"})
    ),
    "add_resume": MatrixFixture(
        {
            "enrollment_id": str(ENROLLMENT),
            "label": "Resume",
            "drive_url": DRIVE_URL,
        },
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "update_resume": MatrixFixture(
        {"enrollment_id": str(ENROLLMENT), "resume_id": str(RESUME)},
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "set_default_resume": MatrixFixture(
        {"enrollment_id": str(ENROLLMENT), "resume_id": str(RESUME)},
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "delete_resume": MatrixFixture(
        {"enrollment_id": str(ENROLLMENT), "resume_id": str(RESUME)},
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "bulk_upsert_profiles": MatrixFixture(
        {"rows": [], "batch_key": "matrix"}, frozenset({"admin"})
    ),
    "delete_staged_row": MatrixFixture(
        {"staged_row_id": str(STAGED_ROW)}, frozenset({"admin"})
    ),
    "create_company": MatrixFixture({"name": "Acme"}, STAFF),
    "update_company": MatrixFixture({"company_id": str(COMPANY)}, STAFF),
    "deactivate_company": MatrixFixture(
        {"company_id": str(COMPANY)}, frozenset({"admin"})
    ),
    "activate_company": MatrixFixture({"company_id": str(COMPANY)}, frozenset({"admin"})),
    "contact_create": MatrixFixture(
        {"company_id": str(COMPANY), "name": "Recruiter", "email": "r@acme.example"}, STAFF
    ),
    "contact_update": MatrixFixture(
        {"company_id": str(COMPANY), "contact_id": str(CONTACT)}, STAFF
    ),
    "contact_delete": MatrixFixture(
        {"company_id": str(COMPANY), "contact_id": str(CONTACT)}, STAFF
    ),
    "merge_companies": MatrixFixture(
        {"survivor_id": str(COMPANY), "duplicate_id": str(OTHER_COMPANY)},
        frozenset({"admin"}),
    ),
    "create_cycle": MatrixFixture(
        {"name": "Placement 2026", "kind": "placement"}, frozenset({"admin"})
    ),
    "update_cycle": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "description": "Edited"}, frozenset({"admin"})
    ),
    "set_cycle_active": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "is_active": True}, frozenset({"admin"})
    ),
    "update_cycle_policy": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "strike_on_absence": False}, frozenset({"admin"})
    ),
    "assign_coordinator": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "user_id": str(USER)}, frozenset({"admin"})
    ),
    "remove_coordinator": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "user_id": str(USER)}, frozenset({"admin"})
    ),
    "join_cycle": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "enrollment_id": str(ENROLLMENT),
            "default_resume_id": str(RESUME_DEFAULT),
            "consent": True,
        },
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    # APP-1 is student-only: a coordinator is a student too (C2), so both
    # coordinators are allowed here and staff-ness is irrelevant.
    "apply": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "enrollment_id": str(ENROLLMENT),
        },
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "edit_application": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "enrollment_id": str(ENROLLMENT),
            "application_id": str(APPLICATION),
        },
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "withdraw_application": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "enrollment_id": str(ENROLLMENT),
            "application_id": str(APPLICATION),
        },
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "advance_applications": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "rows": [],
            "batch_key": "matrix-advance_applications",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "eliminate_applications": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "rows": [],
            "batch_key": "matrix-eliminate_applications",
            "reason": "Matrix",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "waitlist_applications": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "rows": [],
            "batch_key": "matrix-waitlist_applications",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "promote_waitlisted": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "rows": [],
            "batch_key": "matrix-promote_waitlisted",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "mark_attendance": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "round_id": str(ROUND),
            "application_id": str(APPLICATION),
            "attendance": "present",
            "expected_attendance": "pending",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "bulk_mark_present": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "round_id": str(ROUND),
            "rows": [],
            "batch_key": "matrix-bulk_mark_present",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "bulk_mark_absent": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "round_id": str(ROUND),
            "rows": [],
            "batch_key": "matrix-bulk_mark_absent",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "assign_venue_timing": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "round_id": str(ROUND),
            "rows": [],
            "batch_key": "matrix-assign_venue_timing",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "finalize_round": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "round_id": str(ROUND),
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "extend_offers": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "rows": [],
            "batch_key": "matrix-extend-offers",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "accept_offer": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "application_id": str(APPLICATION),
            "offer_id": str(OFFER),
            "enrollment_id": str(ENROLLMENT),
            "expected_status": "offered",
        },
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "decline_offer": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "application_id": str(APPLICATION),
            "offer_id": str(OFFER),
            "enrollment_id": str(ENROLLMENT),
            "expected_status": "offered",
        },
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "record_open_outcome": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "target_status": "offered",
            "rows": [],
            "batch_key": "matrix-record-open-outcome",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "terminate_offer": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "application_id": str(APPLICATION),
            "offer_id": str(OFFER),
            "expected_status": "accepted",
            "termination_kind": "admin_correction",
            "reason": "Matrix correction",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "re_extend_offer": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "application_id": str(APPLICATION),
            "offer_id": str(OFFER),
            "expected_status": "declined",
            "reason": "Matrix re-extension",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "create_external_offer": MatrixFixture(
        {
            "enrollment_id": str(ENROLLMENT),
            "company_id": str(COMPANY),
            "outcome": "placement",
            "source": "off_campus",
            "reason": "Matrix record",
        },
        STAFF,
    ),
    "update_external_offer": MatrixFixture(
        {
            "external_offer_id": str(OFFER),
            "expected_status": "offered",
            "reason": "Matrix update",
        },
        STAFF,
    ),
    "delete_external_offer": MatrixFixture(
        {
            "external_offer_id": str(OFFER),
            "expected_status": "offered",
            "reason": "Matrix delete",
        },
        STAFF,
    ),
    "attach_external_offer": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "external_offer_id": str(OFFER),
            "reason": "Matrix attachment",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "attach_external_offers": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "rows": [],
            "batch_key": "matrix-external-attachment",
            "reason": "Matrix attachments",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "detach_external_offer": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "external_offer_id": str(OFFER),
            "expected_attached_cycle_id": str(CYCLE_A),
            "reason": "Matrix detachment",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    # Discipline is enrollment-scoped and admin-only (INT-1): a coordinator of
    # the cycle the absence happened in still cannot award or revoke.
    "award_strike": MatrixFixture(
        {"enrollment_id": str(ENROLLMENT), "reason": "Matrix"},
        frozenset({"admin"}),
    ),
    "revoke_strike": MatrixFixture(
        {"strike_id": str(STRIKE), "reason": "Matrix"},
        frozenset({"admin"}),
    ),
    "award_penalty": MatrixFixture(
        {"enrollment_id": str(ENROLLMENT), "reasons": "Matrix"},
        frozenset({"admin"}),
    ),
    "revoke_penalty": MatrixFixture(
        {"penalty_id": str(PENALTY), "reason": "Matrix"},
        frozenset({"admin"}),
    ),
    "approve_memberships": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "rows": [], "batch_key": "matrix"},
        frozenset({"coordinator_a", "admin"}),
    ),
    "reject_membership": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "membership_id": str(MEMBERSHIP),
            "reason": "Incomplete",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "rerequest_membership": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "enrollment_id": str(ENROLLMENT),
            "default_resume_id": str(RESUME_DEFAULT),
            "consent": True,
        },
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "set_outcome_tag": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "membership_id": str(MEMBERSHIP),
            "outcome_tag": "higher_studies",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "withdraw_membership": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "enrollment_id": str(ENROLLMENT)},
        frozenset({"student", "coordinator_a", "coordinator_b"}),
    ),
    "remove_membership": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "membership_id": str(MEMBERSHIP),
            "reason": "Code of conduct",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "restore_membership": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "membership_id": str(MEMBERSHIP)},
        frozenset({"coordinator_a", "admin"}),
    ),
    "archive_cycle": MatrixFixture(
        {"cycle_id": str(CYCLE_A)}, frozenset({"admin"})
    ),
    "create_job": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "company_id": str(COMPANY),
            "title": "Backend Engineer",
            "description": "Build things",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "update_job_basics": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "job_id": str(JOB), "title": "Renamed"},
        frozenset({"coordinator_a", "admin"}),
    ),
    "update_job_eligibility": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "job_id": str(JOB)},
        frozenset({"coordinator_a", "admin"}),
    ),
    "upsert_job_rounds": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "job_id": str(JOB), "rounds": []},
        frozenset({"coordinator_a", "admin"}),
    ),
    "upsert_job_questions": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "job_id": str(JOB), "questions": []},
        frozenset({"coordinator_a", "admin"}),
    ),
    "publish_job": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "job_id": str(JOB)},
        frozenset({"coordinator_a", "admin"}),
    ),
    "unpublish_job": MatrixFixture(
        {"cycle_id": str(CYCLE_A), "job_id": str(JOB)},
        frozenset({"coordinator_a", "admin"}),
    ),
    "cancel_job": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "rows": [],
            "batch_key": "matrix-cancel",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "save_export_preset": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "columns": ["roll_number"],
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "request_export": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "job_id": str(JOB),
            "kind": "job_applications",
            "columns": ["roll_number"],
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    # The deferred half of ANA-4 is the worker's, never a request's: it is
    # registered without an HTTP route and answers to the system actor alone.
    "complete_export": MatrixFixture(
        {"export_id": "00000000-0000-0000-0000-0000000004e1"},
        frozenset(),
    ),
    "upsert_taxonomy_item": MatrixFixture(
        {"kind": "sectors", "name": "Technology"}, frozenset({"admin"})
    ),
    "set_setting": MatrixFixture(
        {"key": "session_hours", "value": 24}, frozenset({"admin"})
    ),
    # A cycle-scoped grant is the coordinator's to make inside their own cycle;
    # the route stage sees the cycle it names, and the in-executor check sees
    # the cycle the target really sits in.
    "create_override": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "rule_domain": "application_deadline",
            "reason": "Late application",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    # The override's own cycle is not on the wire, so only the loaded-scope
    # check can place it: at the route stage every coordinator is let through
    # and the second check is what refuses the wrong one (invariant 8).
    "deactivate_override": MatrixFixture(
        {"override_id": str(OVERRIDE)}, STAFF
    ),
    "reinstate_application": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "application_id": str(APPLICATION),
            "reason": "Eliminated in error",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    "force_transition": MatrixFixture(
        {
            "cycle_id": str(CYCLE_A),
            "application_id": str(APPLICATION),
            "to_status": "withdrawn",
            "reason": "Manual correction",
        },
        frozenset({"coordinator_a", "admin"}),
    ),
    # Findings are portal-wide drift, so their verdicts are administrative.
    "resolve_finding": MatrixFixture(
        {"finding_id": str(FINDING), "reason": "Compensated"},
        frozenset({"admin"}),
    ),
    "dismiss_finding": MatrixFixture(
        {"finding_id": str(FINDING), "reason": "Expected"},
        frozenset({"admin"}),
    ),
    # The nightly pass runs as the system; an administrator may also run it on
    # demand, which is the whole of the design review section 4.36. Neither coordinator
    # can: a checker run writes findings about every cycle at once.
    "run_consistency_checker": MatrixFixture({}, frozenset({"admin"})),
}


SCREEN_ALLOWED = {
    "staff/cycles": STAFF,
    "staff/cycle/{id}": STAFF,
    "staff/cycle/{id}/approvals": STAFF,
    "cycles/joinable": frozenset({"student", "coordinator_a", "coordinator_b"}),
    "staff/cycle/{id}/jobs": STAFF,
    "staff/job/{id}/builder": STAFF,
    "cycle/{id}/jobs": frozenset({"student", "coordinator_a", "coordinator_b"}),
    "job/{id}": frozenset({"student", "coordinator_a", "coordinator_b"}),
    "staff/companies": STAFF,
    "staff/company/{id}": STAFF,
    "me/profile": frozenset({"student", "coordinator_a", "coordinator_b"}),
    "me/applications": frozenset({"student", "coordinator_a", "coordinator_b"}),
    "me/notifications": frozenset({"student", "coordinator_a", "coordinator_b"}),
    "staff/job/{id}/board": STAFF,
    "staff/job/{id}/offers": STAFF,
    "staff/external": STAFF,
    "staff/cycle/{id}/external": STAFF,
    "me/dashboard": frozenset({"student", "coordinator_a", "coordinator_b"}),
    "admin/bulk-upsert": frozenset({"admin"}),
    "admin/discipline": frozenset({"admin"}),
    "admin/taxonomies": frozenset({"admin"}),
    # The same lists, readable by staff: the JOB-1 builder cannot pick a sector,
    # a round type or a rule's programs without them.
    "staff/taxonomies": STAFF,
    "admin/settings": frozenset({"admin"}),
    "admin/users": frozenset({"admin"}),
    "admin/templates": frozenset({"admin"}),
    # INT-2 grants create_override to staff of the cycle, so the register that
    # shows what they granted is theirs to read; the query scopes each
    # coordinator to their own cycles.
    "admin/overrides": STAFF,
    "admin/findings": frozenset({"admin"}),
    "staff/student/{enrollment_id}": STAFF,
    "staff/cycle/{id}/analytics": STAFF,
    "staff/job/{id}/analytics": STAFF,
    # ANA-2 puts the portal trend behind the administrator: it spans every
    # cycle, including the ones a given coordinator does not run.
    "admin/analytics/portal": frozenset({"admin"}),
}


ACTORS = {
    "anon": ActorContext(principal_id="anonymous"),
    "student": ActorContext(
        principal_id=str(USER), user_id=USER, role="student", session_id=SESSION,
        current_enrollment_id=ENROLLMENT,
    ),
    "coordinator_a": ActorContext(
        principal_id=str(USER), user_id=USER, role="student", session_id=SESSION,
        current_enrollment_id=ENROLLMENT, coordinated_cycle_ids=(CYCLE_A,),
    ),
    "coordinator_b": ActorContext(
        principal_id=str(USER), user_id=USER, role="student", session_id=SESSION,
        current_enrollment_id=ENROLLMENT, coordinated_cycle_ids=(CYCLE_B,),
    ),
    "admin": ActorContext(
        principal_id=str(USER), user_id=USER, role="admin", session_id=SESSION,
    ),
}


def _settings() -> Settings:
    return Settings(
        session_secret="matrix-test-session-secret-32-characters",
        dev_login=False,
    )


def test_IDN3_authz_matrix_has_a_fixture_for_every_production_registry_entry() -> None:
    registry = build_registry(settings=_settings())
    assert set(FIXTURES) == set(registry.commands)
    assert set(SCREEN_ALLOWED) == set(registry.screens)


@pytest.mark.parametrize("command_name", sorted(FIXTURES))
@pytest.mark.parametrize("actor_name", tuple(ACTORS))
def test_IDN3_generated_command_authorization_matrix(
    command_name: str, actor_name: str
) -> None:
    registry = build_registry(settings=_settings())
    spec = registry.commands[command_name]
    fixture = FIXTURES[command_name]
    input_value = spec.input_model.model_validate(fixture.input)

    if actor_name in fixture.allowed:
        Authorizer().check(spec, ACTORS[actor_name], input_value)
    else:
        with pytest.raises(AuthorizationDenied):
            Authorizer().check(spec, ACTORS[actor_name], input_value)


@pytest.mark.parametrize("screen_id", sorted(SCREEN_ALLOWED))
@pytest.mark.parametrize("actor_name", tuple(ACTORS))
def test_IDN3_generated_screen_authorization_matrix(
    screen_id: str, actor_name: str
) -> None:
    registry = build_registry(settings=_settings())
    spec = registry.screens[screen_id]
    if actor_name in SCREEN_ALLOWED[screen_id]:
        Authorizer().check_screen(spec, ACTORS[actor_name])
    else:
        with pytest.raises(AuthorizationDenied):
            Authorizer().check_screen(spec, ACTORS[actor_name])
