"""M2 end-to-end harness for Behavior section 16 guarantees."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.bootstrap import build_registry
from app.core.db import create_engine
from app.core.plan import ActorContext, Preview, Result
from app.main import create_app
from app.modules.identity.session import hash_session_token
from app.settings import Settings
from app.worker import create_procrastinate_app
from tests.notifications.seed_defaults import restore_migration_defaults

APP_DATABASE_URL = os.environ["TEST_DATABASE_URL"]
ADMIN = UUID("00000000-0000-0000-0000-000000000301")
ADMIN_SESSION = UUID("00000000-0000-0000-0000-000000000311")
STUDENT = UUID("00000000-0000-0000-0000-000000000305")
STUDENT_SESSION = UUID("00000000-0000-0000-0000-000000000315")
STUDENT_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000325")
RESUME_A = UUID("00000000-0000-0000-0000-000000000331")
RESUME_B = UUID("00000000-0000-0000-0000-000000000332")
STAGED_ROW = UUID("00000000-0000-0000-0000-000000000341")
DRIVE_URL = "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOpQrStUvWxYz012345/view"
COMPANY_A = UUID("00000000-0000-0000-0000-000000000351")
COMPANY_B = UUID("00000000-0000-0000-0000-000000000352")
COMPANY_C = UUID("00000000-0000-0000-0000-000000000353")
CONTACT_A = UUID("00000000-0000-0000-0000-000000000361")
CYCLE_A = UUID("00000000-0000-0000-0000-000000000371")
CYCLE_OPEN = UUID("00000000-0000-0000-0000-000000000372")
MEMBERSHIP_A = UUID("00000000-0000-0000-0000-000000000381")
MEMBERSHIP_B = UUID("00000000-0000-0000-0000-000000000382")
MEMBERSHIP_C = UUID("00000000-0000-0000-0000-000000000383")
# Subjects that exist so a fixture does not have to stand on another fixture's
# execution: the parity test runs the table in dict order, which quietly let
# `remove_membership` depend on `approve_memberships` having gone first.
REMOVABLE_MEMBER = UUID("00000000-0000-0000-0000-000000000309")
REMOVABLE_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000329")
MEMBERSHIP_ACTIVE = UUID("00000000-0000-0000-0000-000000000385")
RESTORABLE_MEMBER = UUID("00000000-0000-0000-0000-000000000310")
RESTORABLE_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000330")
MEMBERSHIP_REMOVED = UUID("00000000-0000-0000-0000-000000000386")
REMOVABLE_COORDINATOR = UUID("00000000-0000-0000-0000-000000000303")
# M11 subjects.  One apiece, because these commands move a status or a
# disciplinary record and sharing one would make each fixture's meaning depend
# on the table's ordering (the design review section 4.24).
STRIKE_SUBJECT = UUID("00000000-0000-0000-0000-000000000401")
STRIKE_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000411")
REVOKE_STRIKE_SUBJECT = UUID("00000000-0000-0000-0000-000000000402")
REVOKE_STRIKE_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000412")
HARNESS_STRIKE = UUID("00000000-0000-0000-0000-000000000421")
PENALTY_SUBJECT = UUID("00000000-0000-0000-0000-000000000403")
PENALTY_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000413")
REVOKE_PENALTY_SUBJECT = UUID("00000000-0000-0000-0000-000000000404")
REVOKE_PENALTY_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000414")
HARNESS_PENALTY = UUID("00000000-0000-0000-0000-000000000422")
FINALIZE_SUBJECT = UUID("00000000-0000-0000-0000-000000000405")
FINALIZE_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000415")
FINALIZE_ROUND = UUID("00000000-0000-0000-0000-000000000431")
FINALIZE_APPLICATION = UUID("00000000-0000-0000-0000-000000000441")
# M12b portal-offer subjects.  Acceptance and decline cannot share an
# application because the parity loop executes each fixture after previewing it.
OFFER_ACCEPT_JOB = UUID("00000000-0000-0000-0000-000000000451")
OFFER_DECLINE_JOB = UUID("00000000-0000-0000-0000-000000000452")
OFFER_OPEN_JOB = UUID("00000000-0000-0000-0000-000000000453")
OFFER_ACCEPT_APPLICATION = UUID("00000000-0000-0000-0000-000000000461")
OFFER_DECLINE_APPLICATION = UUID("00000000-0000-0000-0000-000000000462")
OFFER_ACCEPT = UUID("00000000-0000-0000-0000-000000000471")
OFFER_DECLINE = UUID("00000000-0000-0000-0000-000000000472")
OFFER_TERMINATE_JOB = UUID("00000000-0000-0000-0000-000000000454")
OFFER_REEXTEND_JOB = UUID("00000000-0000-0000-0000-000000000455")
OFFER_TERMINATE_APPLICATION = UUID("00000000-0000-0000-0000-000000000463")
OFFER_REEXTEND_APPLICATION = UUID("00000000-0000-0000-0000-000000000464")
OFFER_TERMINATE = UUID("00000000-0000-0000-0000-000000000473")
OFFER_REEXTEND = UUID("00000000-0000-0000-0000-000000000474")
EXTERNAL_UPDATE = UUID("00000000-0000-0000-0000-000000000481")
EXTERNAL_DELETE = UUID("00000000-0000-0000-0000-000000000482")
EXTERNAL_ATTACH = UUID("00000000-0000-0000-0000-000000000483")
EXTERNAL_DETACH = UUID("00000000-0000-0000-0000-000000000484")
DEAD_NOTIFICATION = UUID("00000000-0000-0000-0000-000000000491")
# M14 subjects.  Each intervention gets its own application for the reason
# section 4.24 gave: the parity loop executes every fixture after previewing it,
# so two fixtures sharing a subject would make each one's meaning depend on the
# order the table happens to be written in.
REINSTATE_JOB = UUID("00000000-0000-0000-0000-000000000501")
FORCE_JOB = UUID("00000000-0000-0000-0000-000000000502")
REINSTATE_APPLICATION = UUID("00000000-0000-0000-0000-000000000511")
FORCE_APPLICATION = UUID("00000000-0000-0000-0000-000000000512")
REINSTATE_ROUND = UUID("00000000-0000-0000-0000-000000000521")
HARNESS_OVERRIDE = UUID("00000000-0000-0000-0000-000000000531")
RESOLVE_FINDING = UUID("00000000-0000-0000-0000-000000000541")
DISMISS_FINDING = UUID("00000000-0000-0000-0000-000000000542")
# A second student with a declared, complete profile: the M6 fixtures need
# STUDENT_ENROLLMENT to stay undeclared, and joining needs the opposite.
JOINER = UUID("00000000-0000-0000-0000-000000000307")
JOINER_SESSION = UUID("00000000-0000-0000-0000-000000000317")
JOINER_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000327")
JOINER_RESUME = UUID("00000000-0000-0000-0000-000000000333")
HARNESS_PROGRAM = UUID("00000000-0000-0000-0000-000000000391")
HARNESS_BRANCH = UUID("00000000-0000-0000-0000-000000000392")
COORDINATOR = UUID("00000000-0000-0000-0000-000000000302")
HARNESS_JOB = UUID("00000000-0000-0000-0000-000000000393")
HARNESS_ROUND_TYPE = UUID("00000000-0000-0000-0000-000000000394")
# APP-1's parity fixture owns its own student and its own published job: every
# other job fixture publishes, unpublishes or cancels HARNESS_JOB, so applying
# to it would make this run depend on the order the fixture table is written in.
APPLICANT = UUID("00000000-0000-0000-0000-000000000308")
APPLICANT_SESSION = UUID("00000000-0000-0000-0000-000000000318")
APPLICANT_ENROLLMENT = UUID("00000000-0000-0000-0000-000000000328")
APPLICANT_RESUME = UUID("00000000-0000-0000-0000-000000000334")
APPLICANT_MEMBERSHIP = UUID("00000000-0000-0000-0000-000000000384")
APPLY_JOB = UUID("00000000-0000-0000-0000-000000000395")
# APP-3's two fixtures each own an application on their own (job, enrollment)
# pair: the partial-unique index allows only one live application per pair, and
# withdrawing one would leave the other fixture editing a withdrawn row.
LIFECYCLE_JOB = UUID("00000000-0000-0000-0000-000000000396")
LIFECYCLE_ROUND = UUID("00000000-0000-0000-0000-000000000399")
EDITABLE_APPLICATION = UUID("00000000-0000-0000-0000-000000000397")
WITHDRAWABLE_APPLICATION = UUID("00000000-0000-0000-0000-000000000398")
WORKER_DATABASE_URL = os.environ["TEST_PROCRASTINATE_DATABASE_URL"]


def harness_settings() -> Settings:
    """Explicit settings, so session tokens can be hashed the way the app will."""
    return Settings(
        session_secret="harness-http-ratchet-session-secret-32ch",
        dev_login=False,
    )


#: Raw session tokens by session id.  The fixtures name an ``ActorContext``
#: directly, which is all the executor needs; a *route* needs the cookie that
#: produces that actor, so the two are kept in step here.
SESSION_TOKENS: dict[UUID, str] = {
    ADMIN_SESSION: "harness-admin-session",
    STUDENT_SESSION: "harness-student-session",
    JOINER_SESSION: "harness-joiner-session",
    APPLICANT_SESSION: "harness-applicant-session",
}


def session_hash(session_id: UUID) -> str:
    return hash_session_token(SESSION_TOKENS[session_id], harness_settings().session_secret)


@dataclass(frozen=True, slots=True)
class PreviewFixture:
    input: dict[str, object]
    actor: ActorContext


PREVIEW_FIXTURES = {
    "ping": PreviewFixture(
        input={"recipient": "parity@example.edu"},
        actor=ActorContext(principal_id="harness", is_test_harness=True),
    ),
    "start_new_enrollment": PreviewFixture(
        input={"user_id": "00000000-0000-0000-0000-000000000302"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "set_user_role": PreviewFixture(
        input={"user_id": "00000000-0000-0000-0000-000000000303", "role": "admin"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "deactivate_user": PreviewFixture(
        input={"user_id": "00000000-0000-0000-0000-000000000304"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "logout": PreviewFixture(
        input={},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "declare_profile": PreviewFixture(
        input={
            "enrollment_id": str(STUDENT_ENROLLMENT),
            "fields": {"personal_email": "harness@example.com", "roll_number": "HARNESS01"},
        },
        actor=ActorContext(
            principal_id=str(STUDENT),
            user_id=STUDENT,
            role="student",
            session_id=STUDENT_SESSION,
            current_enrollment_id=STUDENT_ENROLLMENT,
        ),
    ),
    "update_student_fields": PreviewFixture(
        input={
            "enrollment_id": str(JOINER_ENROLLMENT),
            "fields": {"contact_number": "+1 202-555-0101"},
        },
        # The joiner, not the student: PRO-1 refuses an edit before declaration,
        # and the student's profile is declared by another fixture rather than
        # by the world.
        actor=ActorContext(
            principal_id=str(JOINER),
            user_id=JOINER,
            role="student",
            session_id=JOINER_SESSION,
            current_enrollment_id=JOINER_ENROLLMENT,
        ),
    ),
    "admin_update_profile": PreviewFixture(
        input={"enrollment_id": str(STUDENT_ENROLLMENT), "fields": {"cpi": "8.50"}},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "add_resume": PreviewFixture(
        input={
            "enrollment_id": str(STUDENT_ENROLLMENT),
            "label": "Harness resume",
            "drive_url": DRIVE_URL,
        },
        actor=ActorContext(
            principal_id=str(STUDENT),
            user_id=STUDENT,
            role="student",
            session_id=STUDENT_SESSION,
            current_enrollment_id=STUDENT_ENROLLMENT,
        ),
    ),
    "update_resume": PreviewFixture(
        input={
            "enrollment_id": str(STUDENT_ENROLLMENT),
            "resume_id": str(RESUME_A),
            "label": "Renamed",
        },
        actor=ActorContext(
            principal_id=str(STUDENT),
            user_id=STUDENT,
            role="student",
            session_id=STUDENT_SESSION,
            current_enrollment_id=STUDENT_ENROLLMENT,
        ),
    ),
    "set_default_resume": PreviewFixture(
        input={"enrollment_id": str(STUDENT_ENROLLMENT), "resume_id": str(RESUME_B)},
        actor=ActorContext(
            principal_id=str(STUDENT),
            user_id=STUDENT,
            role="student",
            session_id=STUDENT_SESSION,
            current_enrollment_id=STUDENT_ENROLLMENT,
        ),
    ),
    "delete_resume": PreviewFixture(
        input={"enrollment_id": str(STUDENT_ENROLLMENT), "resume_id": str(RESUME_A)},
        actor=ActorContext(
            principal_id=str(STUDENT),
            user_id=STUDENT,
            role="student",
            session_id=STUDENT_SESSION,
            current_enrollment_id=STUDENT_ENROLLMENT,
        ),
    ),
    "bulk_upsert_profiles": PreviewFixture(
        input={
            "rows": [
                {
                    "row_number": 1,
                    "institute_email": "two@example.edu",
                    "fields": {"cpi": "7.10"},
                }
            ],
            "batch_key": "harness-batch",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "delete_staged_row": PreviewFixture(
        input={"staged_row_id": str(STAGED_ROW)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "create_company": PreviewFixture(
        input={"name": "Harness Trading"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "update_company": PreviewFixture(
        input={"company_id": str(COMPANY_A), "description": "Updated by the harness"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "contact_create": PreviewFixture(
        input={
            "company_id": str(COMPANY_A),
            "name": "Second Recruiter",
            "email": "second@harness.example",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "contact_update": PreviewFixture(
        input={
            "company_id": str(COMPANY_A),
            "contact_id": str(CONTACT_A),
            "designation": "Campus Lead",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "contact_delete": PreviewFixture(
        input={"company_id": str(COMPANY_A), "contact_id": str(CONTACT_A)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "deactivate_company": PreviewFixture(
        input={"company_id": str(COMPANY_B)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "activate_company": PreviewFixture(
        input={"company_id": str(COMPANY_B)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "merge_companies": PreviewFixture(
        input={"survivor_id": str(COMPANY_A), "duplicate_id": str(COMPANY_C)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "upsert_taxonomy_item": PreviewFixture(
        input={"kind": "sectors", "name": "Harness Technology"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "set_setting": PreviewFixture(
        input={"key": "session_hours", "value": 24},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "update_template": PreviewFixture(
        input={
            "event_key": "offer_extended",
            "cycle_id": str(CYCLE_A),
            "subject": "Harness offer: {job}",
            "body": "Hello {student}",
            "enabled": True,
        },
        actor=ActorContext(
            principal_id=str(ADMIN),
            user_id=ADMIN,
            role="admin",
            session_id=ADMIN_SESSION,
        ),
    ),
    "resend_notification": PreviewFixture(
        input={"notification_id": str(DEAD_NOTIFICATION)},
        actor=ActorContext(
            principal_id=str(ADMIN),
            user_id=ADMIN,
            role="admin",
            session_id=ADMIN_SESSION,
        ),
    ),
    "create_cycle": PreviewFixture(
        input={"name": "Harness Cycle", "kind": "open"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "update_cycle": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "description": "Harness edit"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "set_cycle_active": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "is_active": True},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "update_cycle_policy": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "deadline_reminder_hours": 8},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "assign_coordinator": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "user_id": str(COORDINATOR)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "remove_coordinator": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "user_id": str(REMOVABLE_COORDINATOR)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "join_cycle": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_OPEN),
            "enrollment_id": str(JOINER_ENROLLMENT),
            "default_resume_id": str(JOINER_RESUME),
            "consent": True,
        },
        actor=ActorContext(
            principal_id=str(JOINER),
            user_id=JOINER,
            role="student",
            session_id=JOINER_SESSION,
            current_enrollment_id=JOINER_ENROLLMENT,
        ),
    ),
    "approve_memberships": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "rows": [{"membership_id": str(MEMBERSHIP_A)}],
            "batch_key": "harness-approvals",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "reject_membership": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "membership_id": str(MEMBERSHIP_B),
            "reason": "Harness rejection",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "rerequest_membership": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "enrollment_id": str(JOINER_ENROLLMENT),
            "default_resume_id": str(JOINER_RESUME),
            "consent": True,
        },
        actor=ActorContext(
            principal_id=str(JOINER),
            user_id=JOINER,
            role="student",
            session_id=JOINER_SESSION,
            current_enrollment_id=JOINER_ENROLLMENT,
        ),
    ),
    "set_outcome_tag": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "membership_id": str(MEMBERSHIP_A),
            "outcome_tag": "higher_studies",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "withdraw_membership": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "enrollment_id": str(STUDENT_ENROLLMENT)},
        actor=ActorContext(
            principal_id=str(STUDENT),
            user_id=STUDENT,
            role="student",
            session_id=STUDENT_SESSION,
            current_enrollment_id=STUDENT_ENROLLMENT,
        ),
    ),
    "restore_membership": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "membership_id": str(MEMBERSHIP_REMOVED)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "remove_membership": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "membership_id": str(MEMBERSHIP_ACTIVE),
            "reason": "Harness removal",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "create_job": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "company_id": str(COMPANY_A),
            "title": "Harness Engineer",
            "description": "Parity fixture",
            "application_deadline": "2030-06-01T00:00:00Z",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "update_job_basics": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(HARNESS_JOB),
            "location": "Gandhinagar",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "update_job_eligibility": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(HARNESS_JOB),
            "eligibility_rule": {"field": "cpi", "op": "gte", "value": 7.5},
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "upsert_job_rounds": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(HARNESS_JOB),
            "rounds": [
                {
                    "round_type_id": str(HARNESS_ROUND_TYPE),
                    "name": "Screening",
                }
            ],
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "upsert_job_questions": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(HARNESS_JOB),
            "questions": [{"text": "Why this role?", "qtype": "longtext", "required": True}],
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "publish_job": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "job_id": str(HARNESS_JOB)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "unpublish_job": PreviewFixture(
        input={"cycle_id": str(CYCLE_A), "job_id": str(HARNESS_JOB)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "save_export_preset": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(HARNESS_JOB),
            "columns": ["roll_number", "full_name"],
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "request_export": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(HARNESS_JOB),
            "kind": "job_applications",
            "columns": ["roll_number", "full_name", "status", "resume_link"],
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "apply": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(APPLY_JOB),
            "enrollment_id": str(APPLICANT_ENROLLMENT),
        },
        actor=ActorContext(
            principal_id=str(APPLICANT),
            user_id=APPLICANT,
            role="student",
            session_id=APPLICANT_SESSION,
            current_enrollment_id=APPLICANT_ENROLLMENT,
        ),
    ),
    "edit_application": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "enrollment_id": str(APPLICANT_ENROLLMENT),
            "application_id": str(EDITABLE_APPLICATION),
        },
        actor=ActorContext(
            principal_id=str(APPLICANT),
            user_id=APPLICANT,
            role="student",
            session_id=APPLICANT_SESSION,
            current_enrollment_id=APPLICANT_ENROLLMENT,
        ),
    ),
    "withdraw_application": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "enrollment_id": str(JOINER_ENROLLMENT),
            "application_id": str(WITHDRAWABLE_APPLICATION),
        },
        actor=ActorContext(
            principal_id=str(JOINER),
            user_id=JOINER,
            role="student",
            session_id=JOINER_SESSION,
            current_enrollment_id=JOINER_ENROLLMENT,
        ),
    ),
    "advance_applications": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "rows": [],
            "batch_key": "harness-advance_applications",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "eliminate_applications": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "rows": [],
            "batch_key": "harness-eliminate_applications",
            "reason": "Harness",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "waitlist_applications": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "rows": [],
            "batch_key": "harness-waitlist_applications",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "promote_waitlisted": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "rows": [],
            "batch_key": "harness-promote_waitlisted",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "mark_attendance": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "round_id": str(LIFECYCLE_ROUND),
            "application_id": str(EDITABLE_APPLICATION),
            "attendance": "present",
            "expected_attendance": "pending",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "bulk_mark_present": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "round_id": str(LIFECYCLE_ROUND),
            "rows": [],
            "batch_key": "harness-bulk_mark_present",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "bulk_mark_absent": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "round_id": str(LIFECYCLE_ROUND),
            "rows": [],
            "batch_key": "harness-bulk_mark_absent",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "assign_venue_timing": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "round_id": str(LIFECYCLE_ROUND),
            "rows": [],
            "batch_key": "harness-assign_venue_timing",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "finalize_round": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(LIFECYCLE_JOB),
            "round_id": str(FINALIZE_ROUND),
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "extend_offers": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(OFFER_ACCEPT_JOB),
            "rows": [],
            "batch_key": "harness-extend-offers",
        },
        actor=ActorContext(
            principal_id=str(ADMIN),
            user_id=ADMIN,
            role="admin",
            session_id=ADMIN_SESSION,
        ),
    ),
    "accept_offer": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(OFFER_ACCEPT_JOB),
            "application_id": str(OFFER_ACCEPT_APPLICATION),
            "offer_id": str(OFFER_ACCEPT),
            "enrollment_id": str(APPLICANT_ENROLLMENT),
            "expected_status": "offered",
        },
        actor=ActorContext(
            principal_id=str(APPLICANT),
            user_id=APPLICANT,
            role="student",
            session_id=APPLICANT_SESSION,
            current_enrollment_id=APPLICANT_ENROLLMENT,
        ),
    ),
    "decline_offer": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(OFFER_DECLINE_JOB),
            "application_id": str(OFFER_DECLINE_APPLICATION),
            "offer_id": str(OFFER_DECLINE),
            "enrollment_id": str(JOINER_ENROLLMENT),
            "expected_status": "offered",
        },
        actor=ActorContext(
            principal_id=str(JOINER),
            user_id=JOINER,
            role="student",
            session_id=JOINER_SESSION,
            current_enrollment_id=JOINER_ENROLLMENT,
        ),
    ),
    "record_open_outcome": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_OPEN),
            "job_id": str(OFFER_OPEN_JOB),
            "target_status": "offered",
            "rows": [],
            "batch_key": "harness-record-open-outcome",
        },
        actor=ActorContext(
            principal_id=str(ADMIN),
            user_id=ADMIN,
            role="admin",
            session_id=ADMIN_SESSION,
        ),
    ),
    "terminate_offer": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(OFFER_TERMINATE_JOB),
            "application_id": str(OFFER_TERMINATE_APPLICATION),
            "offer_id": str(OFFER_TERMINATE),
            "expected_status": "offered",
            "termination_kind": "admin_correction",
            "reason": "Harness correction",
        },
        actor=ActorContext(
            principal_id=str(ADMIN),
            user_id=ADMIN,
            role="admin",
            session_id=ADMIN_SESSION,
        ),
    ),
    "re_extend_offer": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(OFFER_REEXTEND_JOB),
            "application_id": str(OFFER_REEXTEND_APPLICATION),
            "offer_id": str(OFFER_REEXTEND),
            "expected_status": "declined",
            "reason": "Harness re-extension",
        },
        actor=ActorContext(
            principal_id=str(ADMIN),
            user_id=ADMIN,
            role="admin",
            session_id=ADMIN_SESSION,
        ),
    ),
    "create_external_offer": PreviewFixture(
        input={
            "enrollment_id": str(STRIKE_ENROLLMENT),
            "company_id": str(COMPANY_A),
            "outcome": "placement",
            "source": "off_campus",
            "status": "offered",
            "reason": "Harness external record",
        },
        actor=ActorContext(
            principal_id=str(ADMIN), user_id=ADMIN, role="admin", session_id=ADMIN_SESSION
        ),
    ),
    "update_external_offer": PreviewFixture(
        input={
            "external_offer_id": str(EXTERNAL_UPDATE),
            "expected_status": "offered",
            "notes": "Updated by harness",
            "reason": "Harness external update",
        },
        actor=ActorContext(
            principal_id=str(ADMIN), user_id=ADMIN, role="admin", session_id=ADMIN_SESSION
        ),
    ),
    "delete_external_offer": PreviewFixture(
        input={
            "external_offer_id": str(EXTERNAL_DELETE),
            "expected_status": "offered",
            "reason": "Harness external delete",
        },
        actor=ActorContext(
            principal_id=str(ADMIN), user_id=ADMIN, role="admin", session_id=ADMIN_SESSION
        ),
    ),
    "attach_external_offer": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "external_offer_id": str(EXTERNAL_ATTACH),
            "reason": "Harness external attachment",
        },
        actor=ActorContext(
            principal_id=str(ADMIN), user_id=ADMIN, role="admin", session_id=ADMIN_SESSION
        ),
    ),
    "attach_external_offers": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "rows": [],
            "batch_key": "harness-external-attachments",
            "reason": "Harness bulk external attachment",
        },
        actor=ActorContext(
            principal_id=str(ADMIN), user_id=ADMIN, role="admin", session_id=ADMIN_SESSION
        ),
    ),
    "detach_external_offer": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "external_offer_id": str(EXTERNAL_DETACH),
            "expected_attached_cycle_id": str(CYCLE_A),
            "reason": "Harness external detachment",
        },
        actor=ActorContext(
            principal_id=str(ADMIN), user_id=ADMIN, role="admin", session_id=ADMIN_SESSION
        ),
    ),
    "award_strike": PreviewFixture(
        input={
            "enrollment_id": str(STRIKE_ENROLLMENT),
            "reason": "Harness strike",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "revoke_strike": PreviewFixture(
        input={"strike_id": str(HARNESS_STRIKE), "reason": "Harness revocation"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "award_penalty": PreviewFixture(
        input={
            "enrollment_id": str(PENALTY_ENROLLMENT),
            "reasons": "Harness penalty",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "revoke_penalty": PreviewFixture(
        input={"penalty_id": str(HARNESS_PENALTY), "reason": "Harness revocation"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "cancel_job": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "job_id": str(HARNESS_JOB),
            "rows": [],
            "batch_key": "harness-cancel",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "create_override": PreviewFixture(
        input={
            "rule_domain": "application_deadline",
            "cycle_id": str(CYCLE_A),
            "reason": "Harness late-application window",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "deactivate_override": PreviewFixture(
        input={"override_id": str(HARNESS_OVERRIDE), "reason": "Harness revocation"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "reinstate_application": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "application_id": str(REINSTATE_APPLICATION),
            "target_round_id": str(REINSTATE_ROUND),
            "reason": "Harness reinstatement",
            "notify": False,
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "force_transition": PreviewFixture(
        input={
            "cycle_id": str(CYCLE_A),
            "application_id": str(FORCE_APPLICATION),
            "to_status": "withdrawn",
            "reason": "Harness forced transition",
        },
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "resolve_finding": PreviewFixture(
        input={"finding_id": str(RESOLVE_FINDING), "reason": "Harness resolution"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    # Exposed since the design review section 4.36: the same run the worker performs at
    # 03:00, triggered by the administrator who just repaired something.
    "run_consistency_checker": PreviewFixture(
        input={},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "dismiss_finding": PreviewFixture(
        input={"finding_id": str(DISMISS_FINDING), "reason": "Harness dismissal"},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
    "archive_cycle": PreviewFixture(
        input={"cycle_id": str(CYCLE_A)},
        actor=ActorContext(
            principal_id="00000000-0000-0000-0000-000000000301",
            user_id=UUID("00000000-0000-0000-0000-000000000301"),
            role="admin",
            session_id=UUID("00000000-0000-0000-0000-000000000311"),
        ),
    ),
}


async def _csrf_headers(client: httpx.AsyncClient) -> dict[str, str]:
    response = await client.get("/me")
    assert response.status_code == 200
    token = client.cookies.get("cds_csrf")
    assert token
    return {"X-CSRF": token}


@pytest_asyncio.fixture(autouse=True)
async def clean_harness_tables() -> None:
    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "TRUNCATE audit_log, idempotency_keys, notification_log, settings, "
                    "consistency_findings, overrides, "
                    "resumes, staged_profile_rows, company_contacts, companies, "
                    "program_branches, programs, branches, minors, sectors, round_types, "
                    "cycle_memberships, cycle_coordinators, cycle_policies, cycles, "
                    "export_presets, job_question_options, job_questions, "
                    "job_program_ctc, job_rounds, jobs, "
                    "profiles, sessions, enrollments, users, "
                    "procrastinate_events, procrastinate_periodic_defers, "
                    "procrastinate_jobs, procrastinate_workers RESTART IDENTITY CASCADE"
                )
            )
            await restore_migration_defaults(connection)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_harness_routes_are_absent_by_default() -> None:
    application = create_app(APP_DATABASE_URL)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ping = await client.post(
                "/api/v1/commands/ping",
                json={"input": {"recipient": "nobody@example.edu"}},
            )
            echo = await client.get("/api/v1/screens/echo?message=hello")

    assert ping.status_code == 404
    assert echo.status_code == 404
    paths = application.openapi()["paths"]
    assert "/api/v1/commands/ping" not in paths
    assert "/api/v1/screens/echo" not in paths


@pytest.mark.asyncio
async def test_echo_screen_is_available_only_in_the_enabled_harness() -> None:
    application = create_app(APP_DATABASE_URL, enable_test_harness=True)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/screens/echo?message=hello")

    assert response.status_code == 200
    assert response.json() == {"message": "hello"}


async def seed_fixture_world(connection: AsyncConnection) -> None:
    """The world every fixture in ``PREVIEW_FIXTURES`` is written against.

    Module-level rather than inline in the parity test because two suites now
    run against it: the parity test, which drives each fixture through the
    executor, and the HTTP ratchet, which drives the same fixture through the
    real route.  A second copy would drift, and the drift would show up as one
    of the two suites quietly testing a different world than it claims to.
    """
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) VALUES "
            "('00000000-0000-0000-0000-000000000301', "
            "'admin@example.edu', 'Admin', 'admin'), "
            "('00000000-0000-0000-0000-000000000302', "
            "'one@example.edu', 'One', 'student'), "
            "('00000000-0000-0000-0000-000000000303', "
            "'two@example.edu', 'Two', 'student'), "
            "('00000000-0000-0000-0000-000000000304', "
            "'three@example.edu', 'Three', 'student')"
        )
    )
    await connection.execute(
        sa.text("INSERT INTO enrollments (user_id, is_current) SELECT id, true FROM users")
    )
    await connection.execute(
        sa.text(
            "INSERT INTO notification_log "
            "(id, recipient, event_key, subject, status, attempts, last_error, context) "
            "VALUES (:id, 'one@example.edu', 'offer_extended', 'Dead offer', "
            "'dead', 5, 'SES unavailable', "
            'CAST(\'{"student":"One","job":"Harness Job",'
            '"company":"Harness Alpha"}\' AS jsonb))'
        ),
        {"id": DEAD_NOTIFICATION},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) VALUES "
            "(:session, :token, "
            "'00000000-0000-0000-0000-000000000301', now() + interval '1 day')"
        ),
        {"session": ADMIN_SESSION, "token": session_hash(ADMIN_SESSION)},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) VALUES "
            "(:student, 'profile@example.edu', 'Profile Student', 'student')"
        ),
        {"student": STUDENT},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current) VALUES (:enrollment, :student, true)"
        ),
        {"enrollment": STUDENT_ENROLLMENT, "student": STUDENT},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:session, :token, :student, "
            "now() + interval '1 day')"
        ),
        {
            "session": STUDENT_SESSION,
            "student": STUDENT,
            "token": session_hash(STUDENT_SESSION),
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO resumes (id, enrollment_id, label, drive_url, is_default) "
            "VALUES (:resume_a, :enrollment, 'Primary', :url, true), "
            "(:resume_b, :enrollment, 'Secondary', :url, false)"
        ),
        {
            "resume_a": RESUME_A,
            "resume_b": RESUME_B,
            "enrollment": STUDENT_ENROLLMENT,
            "url": DRIVE_URL,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO companies (id, name, is_active) VALUES "
            "(:company_a, 'Harness Alpha', true), "
            "(:company_b, 'Harness Beta', true), "
            "(:company_c, 'Harness Gamma', true)"
        ),
        {"company_a": COMPANY_A, "company_b": COMPANY_B, "company_c": COMPANY_C},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO company_contacts "
            "(id, company_id, name, email, is_primary) "
            "VALUES (:contact, :company_a, 'Primary Recruiter', "
            "'primary@harness.example', true)"
        ),
        {"contact": CONTACT_A, "company_a": COMPANY_A},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO staged_profile_rows "
            "(id, institute_email, payload, uploaded_by) "
            "VALUES (:staged, 'nobody@example.edu', "
            "CAST('{\"fields\": {}}' AS jsonb), :admin)"
        ),
        {"staged": STAGED_ROW, "admin": ADMIN},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycles (id, name, kind, is_active) "
            "VALUES (:cycle, 'Harness Placement', 'placement', true)"
        ),
        {"cycle": CYCLE_A},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_policies (cycle_id, "
            "membership_requires_approval, max_accepted_offers, "
            "penalty_blocks_applications, allow_withdrawal_after_deadline, "
            "allow_edit_after_deadline, strike_on_absence) "
            "VALUES (:cycle, true, 1, true, false, false, true)"
        ),
        {"cycle": CYCLE_A},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycles (id, name, kind, is_active) "
            "VALUES (:cycle, 'Harness Open', 'open', true)"
        ),
        {"cycle": CYCLE_OPEN},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_policies (cycle_id, "
            "membership_requires_approval, max_accepted_offers, "
            "penalty_blocks_applications, allow_withdrawal_after_deadline, "
            "allow_edit_after_deadline, strike_on_absence) "
            "VALUES (:cycle, false, NULL, true, false, false, true)"
        ),
        {"cycle": CYCLE_OPEN},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) "
            "VALUES (:id, 'joiner@example.edu', 'Joining Student', 'student')"
        ),
        {"id": JOINER},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current, roll_number) "
            "VALUES (:id, :user_id, true, '21110099')"
        ),
        {"id": JOINER_ENROLLMENT, "user_id": JOINER},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user_id, "
            "now() + interval '1 day')"
        ),
        {
            "id": JOINER_SESSION,
            "user_id": JOINER,
            "token": session_hash(JOINER_SESSION),
        },
    )
    await connection.execute(
        sa.text("INSERT INTO programs (id, name, is_active) VALUES (:id, 'Harness BTech', true)"),
        {"id": HARNESS_PROGRAM},
    )
    await connection.execute(
        sa.text("INSERT INTO branches (id, name, is_active) VALUES (:id, 'Harness CSE', true)"),
        {"id": HARNESS_BRANCH},
    )
    # The joiner's declared profile has to be internally valid: PRO-1 refuses an
    # edit whose program does not offer its branch, so the pair must be linked.
    await connection.execute(
        sa.text("INSERT INTO program_branches (program_id, branch_id) VALUES (:program, :branch)"),
        {"program": HARNESS_PROGRAM, "branch": HARNESS_BRANCH},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO profiles (enrollment_id, program_id, "
            "primary_branch_id, graduating_year, cpi, "
            "active_backlogs, total_backlogs, gender, personal_email, "
            "contact_number, nationality, tenth_percent, tenth_year, "
            "twelfth_percent, twelfth_year, declared_at) "
            "VALUES (:id, :program, :branch, 2026, 8.40, 0, 0, 'female', "
            "'harness.personal@example.com', '+1 202-555-0100', 'IN', "
            "92.00, 2019, 94.00, 2021, now())"
        ),
        {
            "id": JOINER_ENROLLMENT,
            "program": HARNESS_PROGRAM,
            "branch": HARNESS_BRANCH,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO resumes (id, enrollment_id, label, drive_url, "
            "is_default) VALUES (:id, :enrollment, 'Primary', :url, true)"
        ),
        {
            "id": JOINER_RESUME,
            "enrollment": JOINER_ENROLLMENT,
            "url": DRIVE_URL,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, "
            "status, consented_at, rejection_reason) VALUES "
            "(:rejected, :cycle, :enrollment, 'rejected', now(), 'Harness')"
        ),
        {
            "rejected": MEMBERSHIP_C,
            "cycle": CYCLE_A,
            "enrollment": JOINER_ENROLLMENT,
        },
    )
    # Standing subjects for the membership and coordinator fixtures, so each is
    # valid against this world alone rather than against a predecessor's writes.
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) VALUES "
            "(:removable, 'removable@example.edu', 'Removable Member', 'student'), "
            "(:restorable, 'restorable@example.edu', 'Restorable Member', 'student')"
        ),
        {"removable": REMOVABLE_MEMBER, "restorable": RESTORABLE_MEMBER},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current) VALUES "
            "(:removable_enrollment, :removable, true), "
            "(:restorable_enrollment, :restorable, true)"
        ),
        {
            "removable_enrollment": REMOVABLE_ENROLLMENT,
            "removable": REMOVABLE_MEMBER,
            "restorable_enrollment": RESTORABLE_ENROLLMENT,
            "restorable": RESTORABLE_MEMBER,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, "
            "status, consented_at) VALUES "
            "(:active, :cycle, :active_enrollment, 'active', now()), "
            "(:removed, :cycle, :removed_enrollment, 'removed', now())"
        ),
        {
            "active": MEMBERSHIP_ACTIVE,
            "active_enrollment": REMOVABLE_ENROLLMENT,
            "removed": MEMBERSHIP_REMOVED,
            "removed_enrollment": RESTORABLE_ENROLLMENT,
            "cycle": CYCLE_A,
        },
    )
    await connection.execute(
        sa.text("INSERT INTO cycle_coordinators (cycle_id, user_id) VALUES (:cycle, :user)"),
        {"cycle": CYCLE_A, "user": REMOVABLE_COORDINATOR},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, "
            "status, consented_at) VALUES "
            "(:pending, :cycle, :enrollment, 'pending', now())"
        ),
        {
            "pending": MEMBERSHIP_A,
            "cycle": CYCLE_A,
            "enrollment": STUDENT_ENROLLMENT,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) VALUES "
            "(:id, 'applicant@example.edu', 'Applicant', 'student')"
        ),
        {"id": APPLICANT},
    )
    await connection.execute(
        sa.text("INSERT INTO enrollments (id, user_id, is_current) VALUES (:id, :user, true)"),
        {"id": APPLICANT_ENROLLMENT, "user": APPLICANT},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO sessions (id, token_hash, user_id, expires_at) "
            "VALUES (:id, :token, :user, "
            "now() + interval '1 day')"
        ),
        {
            "id": APPLICANT_SESSION,
            "user": APPLICANT,
            "token": session_hash(APPLICANT_SESSION),
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO resumes (id, enrollment_id, label, drive_url, "
            "is_default) VALUES (:id, :enrollment, 'Primary', :url, true)"
        ),
        {
            "id": APPLICANT_RESUME,
            "enrollment": APPLICANT_ENROLLMENT,
            "url": DRIVE_URL,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, "
            "status, consented_at, default_resume_id) VALUES "
            "(:id, :cycle, :enrollment, 'active', now(), :resume)"
        ),
        {
            "id": APPLICANT_MEMBERSHIP,
            "cycle": CYCLE_A,
            "enrollment": APPLICANT_ENROLLMENT,
            "resume": APPLICANT_RESUME,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
            "description, is_published, published_at, "
            "application_deadline) VALUES "
            "(:id, :cycle, :company, 'placement', 'Apply Parity Job', "
            "'Parity fixture', true, now(), now() + interval '30 days')"
        ),
        {"id": APPLY_JOB, "cycle": CYCLE_A, "company": COMPANY_A},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
            "description, is_published, published_at, "
            "application_deadline) VALUES "
            "(:id, :cycle, :company, 'placement', 'Lifecycle Job', "
            "'Parity fixture', true, now(), now() + interval '30 days')"
        ),
        {"id": LIFECYCLE_JOB, "cycle": CYCLE_A, "company": COMPANY_A},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO applications (id, job_id, enrollment_id, status, "
            "resume_url, profile_snapshot, applied_at) VALUES "
            "(:editable, :job, :editor, 'in_progress', :url, "
            "CAST('{}' AS jsonb), now()), "
            "(:withdrawable, :job, :withdrawer, 'in_progress', :url, "
            "CAST('{}' AS jsonb), now())"
        ),
        {
            "editable": EDITABLE_APPLICATION,
            "withdrawable": WITHDRAWABLE_APPLICATION,
            "job": LIFECYCLE_JOB,
            "editor": APPLICANT_ENROLLMENT,
            "withdrawer": JOINER_ENROLLMENT,
            "url": DRIVE_URL,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO round_types (id, name, is_active) VALUES (:id, 'Harness Screening', true)"
        ),
        {"id": HARNESS_ROUND_TYPE},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO job_rounds (id, job_id, round_type_id, name, ord) "
            "VALUES (:id, :job, :round_type, 'Parity Screening', 1)"
        ),
        {
            "id": LIFECYCLE_ROUND,
            "job": LIFECYCLE_JOB,
            "round_type": HARNESS_ROUND_TYPE,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO application_round_states "
            "(application_id, round_id, result, attendance) "
            "VALUES (:application, :round, 'pending', 'pending')"
        ),
        {"application": EDITABLE_APPLICATION, "round": LIFECYCLE_ROUND},
    )
    # M11: one subject per command, and the standing strike and penalty the two
    # revoke fixtures act on.
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) VALUES "
            "(:striker, 'striker@example.edu', 'Strike Subject', 'student'), "
            "(:revoker, 'revoker@example.edu', 'Revoke Subject', 'student'), "
            "(:penalised, 'penalised@example.edu', 'Penalty Subject', 'student'), "
            "(:unpenalised, 'unpenalised@example.edu', 'Revoke Penalty', 'student'), "
            "(:finalised, 'finalised@example.edu', 'Finalize Subject', 'student')"
        ),
        {
            "striker": STRIKE_SUBJECT,
            "revoker": REVOKE_STRIKE_SUBJECT,
            "penalised": PENALTY_SUBJECT,
            "unpenalised": REVOKE_PENALTY_SUBJECT,
            "finalised": FINALIZE_SUBJECT,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current) VALUES "
            "(:striker_e, :striker, true), (:revoker_e, :revoker, true), "
            "(:penalised_e, :penalised, true), (:unpenalised_e, :unpenalised, true), "
            "(:finalised_e, :finalised, true)"
        ),
        {
            "striker_e": STRIKE_ENROLLMENT,
            "striker": STRIKE_SUBJECT,
            "revoker_e": REVOKE_STRIKE_ENROLLMENT,
            "revoker": REVOKE_STRIKE_SUBJECT,
            "penalised_e": PENALTY_ENROLLMENT,
            "penalised": PENALTY_SUBJECT,
            "unpenalised_e": REVOKE_PENALTY_ENROLLMENT,
            "unpenalised": REVOKE_PENALTY_SUBJECT,
            "finalised_e": FINALIZE_ENROLLMENT,
            "finalised": FINALIZE_SUBJECT,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO strikes (id, enrollment_id, reason, source, is_active) "
            "VALUES (:id, :enrollment, 'Seeded strike', 'manual', true)"
        ),
        {"id": HARNESS_STRIKE, "enrollment": REVOKE_STRIKE_ENROLLMENT},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO penalties (id, enrollment_id, reasons, from_strikes, "
            "is_active) VALUES (:id, :enrollment, 'Seeded penalty', false, true)"
        ),
        {"id": HARNESS_PENALTY, "enrollment": REVOKE_PENALTY_ENROLLMENT},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO job_rounds (id, job_id, round_type_id, name, ord) "
            "VALUES (:id, :job, :round_type, 'Parity Finalization', 2)"
        ),
        {
            "id": FINALIZE_ROUND,
            "job": LIFECYCLE_JOB,
            "round_type": HARNESS_ROUND_TYPE,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO applications (id, job_id, enrollment_id, status, "
            "current_round_id, resume_url, profile_snapshot, applied_at) VALUES "
            "(:id, :job, :enrollment, 'in_progress', :round, :url, "
            "CAST('{}' AS jsonb), now())"
        ),
        {
            "id": FINALIZE_APPLICATION,
            "job": LIFECYCLE_JOB,
            "enrollment": FINALIZE_ENROLLMENT,
            "round": FINALIZE_ROUND,
            "url": DRIVE_URL,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO application_round_states "
            "(application_id, round_id, result, attendance) "
            "VALUES (:application, :round, 'pending', 'pending')"
        ),
        {"application": FINALIZE_APPLICATION, "round": FINALIZE_ROUND},
    )
    # M12b/d: independent current offers for every mutating fixture, plus an
    # open job for the empty bulk route fixture.
    await connection.execute(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
            "description, application_deadline, offer_acceptance_deadline) VALUES "
            "(:accept_job, :cycle, :company, 'placement', 'Accept Offer Job', "
            "'Parity fixture', now() + interval '30 days', now() + interval '60 days'), "
            "(:decline_job, :cycle, :company, 'placement', 'Decline Offer Job', "
            "'Parity fixture', now() + interval '30 days', now() + interval '60 days'), "
            "(:terminate_job, :cycle, :company, 'placement', 'Terminate Offer Job', "
            "'Parity fixture', now() + interval '30 days', now() + interval '60 days'), "
            "(:reextend_job, :cycle, :company, 'placement', 'Re-extend Offer Job', "
            "'Parity fixture', now() + interval '30 days', now() + interval '60 days')"
        ),
        {
            "accept_job": OFFER_ACCEPT_JOB,
            "decline_job": OFFER_DECLINE_JOB,
            "terminate_job": OFFER_TERMINATE_JOB,
            "reextend_job": OFFER_REEXTEND_JOB,
            "cycle": CYCLE_A,
            "company": COMPANY_A,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
            "description) VALUES (:id, :cycle, :company, 'internship', "
            "'Open Outcome Job', 'Parity fixture')"
        ),
        {"id": OFFER_OPEN_JOB, "cycle": CYCLE_OPEN, "company": COMPANY_A},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO applications (id, job_id, enrollment_id, status, "
            "resume_url, profile_snapshot, applied_at) VALUES "
            "(:accept_application, :accept_job, :accept_enrollment, 'offered', "
            ":url, CAST('{}' AS jsonb), now()), "
            "(:decline_application, :decline_job, :decline_enrollment, 'offered', "
            ":url, CAST('{}' AS jsonb), now()), "
            "(:terminate_application, :terminate_job, :terminate_enrollment, 'offered', "
            ":url, CAST('{}' AS jsonb), now()), "
            "(:reextend_application, :reextend_job, :reextend_enrollment, 'declined', "
            ":url, CAST('{}' AS jsonb), now())"
        ),
        {
            "accept_application": OFFER_ACCEPT_APPLICATION,
            "accept_job": OFFER_ACCEPT_JOB,
            "accept_enrollment": APPLICANT_ENROLLMENT,
            "decline_application": OFFER_DECLINE_APPLICATION,
            "decline_job": OFFER_DECLINE_JOB,
            "decline_enrollment": JOINER_ENROLLMENT,
            "terminate_application": OFFER_TERMINATE_APPLICATION,
            "terminate_job": OFFER_TERMINATE_JOB,
            "terminate_enrollment": REMOVABLE_ENROLLMENT,
            "reextend_application": OFFER_REEXTEND_APPLICATION,
            "reextend_job": OFFER_REEXTEND_JOB,
            "reextend_enrollment": RESTORABLE_ENROLLMENT,
            "url": DRIVE_URL,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO offers (id, application_id, extended_at, deadline_at) VALUES "
            "(:accept_offer, :accept_application, now(), now() + interval '60 days'), "
            "(:decline_offer, :decline_application, now(), now() + interval '60 days'), "
            "(:terminate_offer, :terminate_application, now(), now() + interval '60 days'), "
            "(:reextend_offer, :reextend_application, now(), now() + interval '60 days')"
        ),
        {
            "accept_offer": OFFER_ACCEPT,
            "accept_application": OFFER_ACCEPT_APPLICATION,
            "decline_offer": OFFER_DECLINE,
            "decline_application": OFFER_DECLINE_APPLICATION,
            "terminate_offer": OFFER_TERMINATE,
            "terminate_application": OFFER_TERMINATE_APPLICATION,
            "reextend_offer": OFFER_REEXTEND,
            "reextend_application": OFFER_REEXTEND_APPLICATION,
        },
    )
    await connection.execute(
        sa.text(
            "UPDATE offers SET response = 'declined', responded_at = now() WHERE id = :offer_id"
        ),
        {"offer_id": OFFER_REEXTEND},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO external_offers (id, enrollment_id, company_id, outcome, "
            "source, status, attached_cycle_id, created_by) VALUES "
            "(:update, :update_enrollment, :company, 'placement', 'off_campus', "
            "'offered', NULL, :admin), "
            "(:delete, :delete_enrollment, :company, 'placement', 'off_campus', "
            "'offered', NULL, :admin), "
            "(:attach, :attach_enrollment, :company, 'placement', 'off_campus', "
            "'offered', NULL, :admin), "
            "(:detach, :detach_enrollment, :company, 'placement', 'off_campus', "
            "'offered', :cycle, :admin)"
        ),
        {
            "update": EXTERNAL_UPDATE,
            "update_enrollment": PENALTY_ENROLLMENT,
            "delete": EXTERNAL_DELETE,
            "delete_enrollment": REVOKE_PENALTY_ENROLLMENT,
            "attach": EXTERNAL_ATTACH,
            "attach_enrollment": REMOVABLE_ENROLLMENT,
            "detach": EXTERNAL_DETACH,
            "detach_enrollment": RESTORABLE_ENROLLMENT,
            "company": COMPANY_A,
            "cycle": CYCLE_A,
            "admin": ADMIN,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
            "description, application_deadline) VALUES "
            "(:id, :cycle, :company, 'placement', 'Harness Job', "
            "'Parity fixture', now() + interval '30 days')"
        ),
        {"id": HARNESS_JOB, "cycle": CYCLE_A, "company": COMPANY_A},
    )
    # M14: two jobs, two applications, one override and two findings.  The
    # reinstatement subject sits in a round it was eliminated in, because the
    # round-state ledger is the half of APP-4.14 a status move cannot show.
    await connection.execute(
        sa.text(
            "INSERT INTO jobs (id, cycle_id, company_id, outcome, title, "
            "description, application_deadline) VALUES "
            "(:reinstate_job, :cycle, :company, 'placement', 'Reinstatement Role', "
            "'Parity fixture', now() + interval '30 days'), "
            "(:force_job, :cycle, :company, 'placement', 'Forced Role', "
            "'Parity fixture', now() + interval '30 days')"
        ),
        {
            "reinstate_job": REINSTATE_JOB,
            "force_job": FORCE_JOB,
            "cycle": CYCLE_A,
            "company": COMPANY_A,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO job_rounds (id, job_id, round_type_id, ord, name) VALUES "
            "(:id, :job_id, :round_type, 1, 'Screening')"
        ),
        {
            "id": REINSTATE_ROUND,
            "job_id": REINSTATE_JOB,
            "round_type": HARNESS_ROUND_TYPE,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO applications (id, job_id, enrollment_id, status, "
            "current_round_id, resume_url, profile_snapshot, applied_at) VALUES "
            "(:reinstate_application, :reinstate_job, :applicant, 'rejected', "
            ":round_id, :url, CAST('{}' AS jsonb), now()), "
            "(:force_application, :force_job, :applicant, 'rejected', NULL, "
            ":url, CAST('{}' AS jsonb), now())"
        ),
        {
            "reinstate_application": REINSTATE_APPLICATION,
            "reinstate_job": REINSTATE_JOB,
            "force_application": FORCE_APPLICATION,
            "force_job": FORCE_JOB,
            "applicant": APPLICANT_ENROLLMENT,
            "round_id": REINSTATE_ROUND,
            "url": DRIVE_URL,
        },
    )
    await connection.execute(
        sa.text(
            "INSERT INTO application_round_states (id, application_id, round_id, "
            "result) VALUES (gen_random_uuid(), :application_id, :round_id, "
            "'eliminated')"
        ),
        {"application_id": REINSTATE_APPLICATION, "round_id": REINSTATE_ROUND},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO overrides (id, rule_domain, allow, cycle_id, reason, "
            "granted_by, is_active) VALUES (:id, 'offer_deadline', true, :cycle, "
            "'Harness standing grant', :admin, true)"
        ),
        {"id": HARNESS_OVERRIDE, "cycle": CYCLE_A, "admin": ADMIN},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO consistency_findings (id, invariant, subject, detail, "
            "status, suggested_fix) VALUES "
            "(:resolve, 'no_open_offer_on_unoffered_application', "
            "CAST('{}' AS jsonb), 'Parity fixture finding', 'open', "
            "'force_transition'), "
            "(:dismiss, 'no_open_offer_on_unoffered_application', "
            "CAST('{\"note\": \"second\"}' AS jsonb), 'Parity fixture finding', "
            "'open', 'force_transition')"
        ),
        {"resolve": RESOLVE_FINDING, "dismiss": DISMISS_FINDING},
    )
    await connection.execute(
        sa.text(
            "INSERT INTO users (id, email, full_name, role) VALUES "
            "('00000000-0000-0000-0000-000000000306', "
            "'queue@example.edu', 'Queue Student', 'student')"
        )
    )
    await connection.execute(
        sa.text(
            "INSERT INTO enrollments (id, user_id, is_current) VALUES "
            "('00000000-0000-0000-0000-000000000326', "
            "'00000000-0000-0000-0000-000000000306', true)"
        )
    )
    await connection.execute(
        sa.text(
            "INSERT INTO cycle_memberships (id, cycle_id, enrollment_id, "
            "status, consented_at) VALUES (:rejectable, :cycle, "
            "'00000000-0000-0000-0000-000000000326', 'pending', now())"
        ),
        {"rejectable": MEMBERSHIP_B, "cycle": CYCLE_A},
    )


@pytest.mark.asyncio
async def test_preview_parity_harness_requires_every_http_command_fixture() -> None:
    registry = build_registry(enable_test_harness=True)
    exposed = {name for name, spec in registry.commands.items() if spec.expose_http}
    assert set(PREVIEW_FIXTURES) == exposed

    application = create_app(APP_DATABASE_URL, enable_test_harness=True)
    async with application.router.lifespan_context(application):
        engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
        try:
            async with engine.begin() as connection:
                await seed_fixture_world(connection)
        finally:
            await engine.dispose()
        executor = application.state.command_executor
        for name, fixture in PREVIEW_FIXTURES.items():
            spec = registry.commands[name]
            input_value = spec.input_model.model_validate(fixture.input)
            preview = await executor.run(name, input_value, fixture.actor, dry_run=True)
            execution = await executor.run(name, input_value, fixture.actor)
            assert isinstance(preview, Preview)
            assert isinstance(execution, Result)
            assert preview.events == execution.events


def http_command_names() -> list[str]:
    """Every command the *production* app routes, which is what users reach.

    Built from the same settings the app under test uses, so an environment
    with ``DEV_LOGIN`` set cannot add a parameter for a route the app will not
    register -- and cannot hide one either.
    """
    registry = build_registry(settings=harness_settings())
    return sorted(name for name, spec in registry.commands.items() if spec.expose_http)


@pytest.mark.asyncio
@pytest.mark.parametrize("command_name", http_command_names())
async def test_every_http_command_answers_over_http(command_name: str) -> None:
    """Every exposed command must survive a real request (the design review section 4.24).

    The preview-parity harness above proves the *decider* agrees with itself,
    and it reaches the executor directly.  Nothing between the route and the
    decider was ever exercised by it: not the request model, not authorization
    from a cookie, and not the response model -- which is how four M10b bulk
    operations shipped answering every real request with a 500, their output
    models naming fields chunk aggregation cannot carry.

    200 is asserted rather than "not a 5xx" because the parity test already
    requires each fixture to succeed at the executor.  Anything else here is a
    defect in the layer this test exists to cover: a 422 means the request
    model rejects the fixture, a 500 means the response model rejects the
    answer.
    """
    fixture = PREVIEW_FIXTURES.get(command_name)
    assert fixture is not None, (
        f"{command_name} has no PREVIEW_FIXTURES entry -- add one naming a valid "
        "input and the actor allowed to send it"
    )
    session_id = fixture.actor.session_id
    assert session_id is not None and session_id in SESSION_TOKENS, (
        f"{command_name}'s fixture actor has no seeded session; add one to "
        "SESSION_TOKENS and seed_fixture_world so the route can authenticate it"
    )

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.begin() as connection:
            await seed_fixture_world(connection)
    finally:
        await engine.dispose()

    application = create_app(APP_DATABASE_URL, settings=harness_settings())
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            client.cookies.set("cds_session", SESSION_TOKENS[session_id])
            headers = await _csrf_headers(client)
            response = await client.post(
                f"/api/v1/commands/{command_name}",
                json={"input": fixture.input, "dry_run": True},
                headers=headers,
            )

    assert response.status_code == 200, (
        f"{command_name} answered {response.status_code}: {response.text[:400]}"
    )
    body = response.json()
    # A 200 carrying the wrong envelope is the other way this fails silently.
    assert set(body) >= {"summary", "events"}, f"{command_name} returned {sorted(body)}"


@pytest.mark.asyncio
async def test_harness_preview_post_requires_csrf() -> None:
    application = create_app(APP_DATABASE_URL, enable_test_harness=True)
    payload = {
        "input": {"recipient": "preview@example.edu"},
        "dry_run": True,
    }
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            rejected = await client.post("/api/v1/commands/ping", json=payload)
            accepted = await client.post(
                "/api/v1/commands/ping",
                json=payload,
                headers=await _csrf_headers(client),
            )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["summary"] == {"accepted": True}


@pytest.mark.asyncio
async def test_outbox_commit_and_future_schedule_waits_for_worker() -> None:
    future = datetime.now(UTC) + timedelta(days=1)
    application = create_app(APP_DATABASE_URL, enable_test_harness=True)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="https://test") as client:
            csrf_headers = await _csrf_headers(client)
            immediate = await client.post(
                "/api/v1/commands/ping",
                json={
                    "input": {"recipient": "immediate@example.edu"},
                    "idempotency_key": "immediate-ping",
                },
                headers=csrf_headers,
            )
            scheduled = await client.post(
                "/api/v1/commands/ping",
                json={
                    "input": {
                        "recipient": "future@example.edu",
                        "schedule_at": future.isoformat(),
                    },
                    "idempotency_key": "future-ping",
                },
                headers=csrf_headers,
            )
        assert immediate.status_code == 200
        assert scheduled.status_code == 200

        worker = create_procrastinate_app(
            conninfo=WORKER_DATABASE_URL,
            executor=application.state.command_executor,
        )
        async with worker.open_async():
            await worker.run_worker_async(
                wait=False,
                listen_notify=False,
                install_signal_handlers=False,
            )

    engine = create_engine(os.environ["TEST_MIGRATION_DATABASE_URL"])
    try:
        async with engine.connect() as connection:
            notifications = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT recipient, status, sent_at FROM notification_log "
                            "ORDER BY recipient"
                        )
                    )
                )
                .mappings()
                .all()
            )
            jobs = (
                (
                    await connection.execute(
                        sa.text(
                            "SELECT args->>'recipient' AS recipient, status, scheduled_at "
                            "FROM procrastinate_jobs "
                            "WHERE task_name = 'deliver_notification' "
                            "ORDER BY args->>'recipient'"
                        )
                    )
                )
                .mappings()
                .all()
            )
            audit_count = await connection.scalar(sa.text("SELECT count(*) FROM audit_log"))
    finally:
        await engine.dispose()

    assert [row["recipient"] for row in notifications] == ["immediate@example.edu"]
    assert notifications[0]["status"] == "sent"
    assert notifications[0]["sent_at"] is not None
    assert [(row["recipient"], row["status"]) for row in jobs] == [
        ("future@example.edu", "todo"),
        ("immediate@example.edu", "succeeded"),
    ]
    assert jobs[0]["scheduled_at"] == future
    assert audit_count == 2
