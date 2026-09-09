"""Canonical reason codes and RFC 7807 exception responses."""

from __future__ import annotations

from dataclasses import asdict
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.plan import Reason, Rejection

NOT_ELIGIBLE = "not_eligible"
DEADLINE_PASSED = "deadline_passed"
DUPLICATE_APPLICATION = "duplicate_application"
PENALTY_ACTIVE = "penalty_active"
OUTCOME_GATE_PLACEMENT = "outcome_gate_placement"
OUTCOME_GATE_INTERNSHIP = "outcome_gate_internship"
OFFER_CAP_REACHED = "offer_cap_reached"
MEMBERSHIP_NOT_ACTIVE = "membership_not_active"
JOB_NOT_FOUND = "job_not_found"
JOB_NOT_OPEN = "job_not_open"
JOB_UNPUBLISHED = "job_unpublished"
JOB_CANCELLED = "job_cancelled"
CYCLE_ARCHIVED = "cycle_archived"
BLOCKED_BY_OVERRIDE = "blocked_by_override"
STALE_VIEW = "stale_view"
WINDOW_CLOSED = "window_closed"
NOT_OFFERED = "not_offered"
OFFER_TERMINATED = "offer_terminated"
INVALID_TRANSITION = "invalid_transition"
UNMATCHED_IDENTIFIER = "unmatched_identifier"
APPLICATION_NOT_FOUND = "application_not_found"
APPLICATION_NOT_EDITABLE = "application_not_editable"
ANSWER_REQUIRED = "answer_required"
ANSWER_INVALID = "answer_invalid"
UNKNOWN_QUESTION = "unknown_question"
RESUME_REQUIRED = "resume_required"
PROFILE_INCOMPLETE = "profile_incomplete"
JOIN_RULE_FAILED = "join_rule_failed"
IDEMPOTENCY_CONFLICT = "idempotency_conflict"
INVALID_REQUEST = "invalid_request"
OUTSIDE_ALLOWED_DOMAIN = "outside_allowed_domain"
INACTIVE_USER = "inactive_user"
SESSION_EFFECT_IDEMPOTENCY = "session_effect_idempotency"
OAUTH_STATE_INVALID = "oauth_state_invalid"
OAUTH_STATE_EXPIRED = "oauth_state_expired"
LAST_ACTIVE_ADMIN = "last_active_admin"
SELF_ADMIN_MUTATION = "self_admin_mutation"
USER_NOT_FOUND = "user_not_found"
OAUTH_CLAIMS_INVALID = "oauth_claims_invalid"
OAUTH_PROVIDER_ERROR = "oauth_provider_error"
TAXONOMY_ITEM_NOT_FOUND = "taxonomy_item_not_found"
TAXONOMY_NAME_CONFLICT = "taxonomy_name_conflict"
ENROLLMENT_NOT_FOUND = "enrollment_not_found"
PROFILE_ALREADY_DECLARED = "profile_already_declared"
PROFILE_NOT_DECLARED = "profile_not_declared"
FIELD_NOT_EDITABLE = "field_not_editable"
INVALID_FIELD_VALUE = "invalid_field_value"
ROLL_NUMBER_TAKEN = "roll_number_taken"
ROLL_MISMATCH = "roll_mismatch"
PROGRAM_BRANCH_MISMATCH = "program_branch_mismatch"
UNKNOWN_TAXONOMY_VALUE = "unknown_taxonomy_value"
INVALID_DRIVE_URL = "invalid_drive_url"
RESUME_NOT_FOUND = "resume_not_found"
LAST_RESUME = "last_resume"
DUPLICATE_ROW = "duplicate_row"
STAGED_ROW_NOT_FOUND = "staged_row_not_found"
STAGED_ROW_ALREADY_APPLIED = "staged_row_already_applied"
UNPARSABLE_UPLOAD = "unparsable_upload"
COMPANY_NOT_FOUND = "company_not_found"
COMPANY_NAME_CONFLICT = "company_name_conflict"
COMPANY_NAME_CONFLICT_INACTIVE = "company_name_conflict_inactive"
COMPANY_INACTIVE = "company_inactive"
CONTACT_NOT_FOUND = "contact_not_found"
CONTACT_EMAIL_CONFLICT = "contact_email_conflict"
MERGE_INTO_SELF = "merge_into_self"
CYCLE_NOT_FOUND = "cycle_not_found"
CYCLE_NAME_CONFLICT = "cycle_name_conflict"
CYCLE_INACTIVE = "cycle_inactive"
REGISTRATION_CLOSED = "registration_closed"
COORDINATOR_NOT_FOUND = "coordinator_not_found"
COORDINATOR_ALREADY_ASSIGNED = "coordinator_already_assigned"
MEMBERSHIP_NOT_FOUND = "membership_not_found"
MEMBERSHIP_EXISTS = "membership_exists"
CONSENT_REQUIRED = "consent_required"
ROUND_ALREADY_FINALIZED = "round_already_finalized"
STRIKE_NOT_FOUND = "strike_not_found"
STRIKE_ALREADY_REVOKED = "strike_already_revoked"
PENALTY_NOT_FOUND = "penalty_not_found"
PENALTY_ALREADY_REVOKED = "penalty_already_revoked"
OVERRIDE_NOT_FOUND = "override_not_found"
OVERRIDE_ALREADY_INACTIVE = "override_already_inactive"
ROUND_NOT_FOUND = "round_not_found"
FINDING_NOT_FOUND = "finding_not_found"
FINDING_NOT_OPEN = "finding_not_open"
UNKNOWN_EXPORT_COLUMN = "unknown_export_column"
EXPORT_NOT_FOUND = "export_not_found"
EXPORT_NOT_READY = "export_not_ready"


class DomainRejection(Exception):
    def __init__(self, rejection: Rejection):
        super().__init__("Command rejected")
        self.rejection = rejection


class RateLimitExceeded(Exception):
    pass


class AuthorizationDenied(Exception):
    def __init__(self, *, authenticated: bool) -> None:
        super().__init__("Forbidden" if authenticated else "Authentication required")
        self.status = 403 if authenticated else 401


class BulkInterrupted(Exception):
    def __init__(
        self,
        *,
        batch_key: str,
        completed_chunks: list[int],
        failed_chunk: int,
        reasons: list[Reason] | None = None,
    ) -> None:
        super().__init__("Bulk execution interrupted")
        self.batch_key = batch_key
        self.completed_chunks = completed_chunks
        self.failed_chunk = failed_chunk
        self.reasons = reasons or []


def _problem(
    *, status: int, type_name: str, title: str, extra: dict[str, object] | None = None
) -> JSONResponse:
    body: dict[str, object] = {
        "type": f"/problems/{type_name}",
        "title": title,
        "status": status,
    }
    if extra:
        body.update(extra)
    return JSONResponse(status_code=status, content=body, media_type="application/problem+json")


def install_exception_handlers(app: FastAPI) -> None:
    async def domain_rejection_handler(
        _request: Request, exception: Exception
    ) -> JSONResponse:
        rejection = cast(DomainRejection, exception)
        return _problem(
            status=409,
            type_name="domain-rejection",
            title="Command rejected",
            extra={"reasons": [asdict(reason) for reason in rejection.rejection.reasons]},
        )

    async def rate_limit_handler(
        _request: Request, _exception: Exception
    ) -> JSONResponse:
        return _problem(status=429, type_name="rate-limit", title="Rate limit exceeded")

    async def authorization_handler(
        _request: Request, exception: Exception
    ) -> JSONResponse:
        denial = cast(AuthorizationDenied, exception)
        return _problem(
            status=denial.status,
            type_name="forbidden" if denial.status == 403 else "authentication-required",
            title="Forbidden" if denial.status == 403 else "Authentication required",
        )

    async def bulk_interrupted_handler(
        _request: Request, exception: Exception
    ) -> JSONResponse:
        interruption = cast(BulkInterrupted, exception)
        status = 409 if interruption.reasons else 500
        extra: dict[str, object] = {
            "batch_key": interruption.batch_key,
            "completed_chunks": interruption.completed_chunks,
            "failed_chunk": interruption.failed_chunk,
            "detail": "Replay with the same batch key to resume",
        }
        if interruption.reasons:
            extra["reasons"] = [asdict(reason) for reason in interruption.reasons]
        return _problem(
            status=status,
            type_name="bulk-interrupted",
            title="Bulk execution interrupted",
            extra=extra,
        )

    async def request_validation_handler(
        _request: Request, exception: Exception
    ) -> JSONResponse:
        validation = cast(RequestValidationError, exception)
        reasons: list[dict[str, object]] = []
        for issue in validation.errors():
            raw_location = issue["loc"]
            if raw_location and raw_location[0] == "body":
                raw_location = raw_location[1:]
            location = [str(part) for part in raw_location]
            reasons.append(
                asdict(
                    Reason(
                        code=INVALID_REQUEST,
                        human=str(issue["msg"]),
                        path=".".join(location) or None,
                    )
                )
            )
        return _problem(
            status=422,
            type_name="request-validation",
            title="Invalid request",
            extra={"reasons": reasons},
        )

    app.add_exception_handler(DomainRejection, domain_rejection_handler)
    app.add_exception_handler(AuthorizationDenied, authorization_handler)
    app.add_exception_handler(RateLimitExceeded, rate_limit_handler)
    app.add_exception_handler(BulkInterrupted, bulk_interrupted_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
