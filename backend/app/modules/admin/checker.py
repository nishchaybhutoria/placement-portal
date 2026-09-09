"""The invariant catalog the nightly consistency pass asserts (LLD section 12).

Every entry is one SQL question with one answer shape: rows that should not
exist.  A row that comes back becomes a finding carrying the invariant, the
subject it names, a detail a human can read, and the *command* that would
compensate for it.

Two structural rules make the catalog trustworthy rather than decorative.

First, the fix is declared beside the detection.  ``FIX_CATALOG`` maps each
invariant to the command that repairs it **and** to the input that command
needs, built from the finding's own subject.  The admin screen renders the
button from that same entry, so the suggestion a finding carries and the
request the button sends cannot drift apart, and a test can dry-run every
suggested fix to prove the button works before an administrator finds out.

Second, detection is pure SQL and nothing here writes: the loader runs these
statements, the decide turns rows into ``StateOp`` inserts.  A checker that
repaired anything itself would be a second write path around the executor.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa

Subject = dict[str, object]


@dataclass(frozen=True, slots=True)
class Invariant:
    """One assertion, its violation query, and how a violation reads."""

    id: str
    #: What the invariant promises, in the words the finding shows.
    description: str
    #: Must return one row per violation.  Column names become the subject's
    #: keys, except ``detail`` which is the human sentence.
    sql: str
    #: The columns that identify the subject, in the order they read.
    subject_columns: tuple[str, ...]
    #: True when the database itself refuses the violating state, so the only
    #: way to reach it is to drop the constraint first.  The injection fixtures
    #: use this to know they must.
    db_backstopped: bool = False


@dataclass(frozen=True, slots=True)
class SuggestedFix:
    """The compensating command for one invariant, and the input it needs."""

    command: str
    #: Builds the command input from the finding's subject.  Returns None when
    #: the subject does not carry enough to prefill it, in which case the screen
    #: shows the command name without a one-click button.
    build_input: Callable[[Subject], dict[str, object] | None]


def _uuid(subject: Subject, key: str) -> UUID | None:
    value = subject.get(key)
    return UUID(str(value)) if value is not None else None


def _terminate_offer(subject: Subject) -> dict[str, object] | None:
    offer_id = _uuid(subject, "offer_id")
    cycle_id = _uuid(subject, "cycle_id")
    job_id = _uuid(subject, "job_id")
    application_id = _uuid(subject, "application_id")
    expected_status = subject.get("stored_status")
    if None in (offer_id, cycle_id, job_id, application_id) or expected_status is None:
        # An accepted *external* offer has no portal offer row to terminate, so
        # the finding names the state and leaves the choice to staff.
        return None
    return {
        "cycle_id": str(cycle_id),
        "job_id": str(job_id),
        "application_id": str(application_id),
        "offer_id": str(offer_id),
        "expected_status": str(expected_status),
        "termination_kind": "admin_correction",
        "reason": "Consistency finding: reconciling the offer record",
        "restore": [],
        "notify": False,
    }


def _force_transition(subject: Subject) -> dict[str, object] | None:
    application_id = _uuid(subject, "application_id")
    cycle_id = _uuid(subject, "cycle_id")
    to_status = subject.get("expected_status")
    if application_id is None or cycle_id is None or to_status is None:
        return None
    return {
        "cycle_id": str(cycle_id),
        "application_id": str(application_id),
        "to_status": str(to_status),
        "reason": "Consistency finding: realigning the stored status with its history",
    }


def _restore_membership(subject: Subject) -> dict[str, object] | None:
    cycle_id = _uuid(subject, "cycle_id")
    membership_id = _uuid(subject, "membership_id")
    if cycle_id is None or membership_id is None:
        return None
    return {"cycle_id": str(cycle_id), "membership_id": str(membership_id)}


def _revoke_penalty(subject: Subject) -> dict[str, object] | None:
    penalty_id = _uuid(subject, "penalty_id")
    if penalty_id is None:
        return None
    return {
        "penalty_id": str(penalty_id),
        "reason": "Consistency finding: the converted penalty has lost its supporting strikes",
    }


def _reinstate(subject: Subject) -> dict[str, object] | None:
    # Deliberately not prefilled.  ``reinstate_application`` rebuilds the
    # round-state ledger, but only for an application that is closed (APP-4.14),
    # and a broken ledger is found on a *live* one.  The repair is therefore two
    # deliberate steps -- close it out, then reinstate to the right round -- and
    # a button that skipped the first would be refused the moment it was pressed.
    del subject
    return None


def _detach_external(subject: Subject) -> dict[str, object] | None:
    external_offer_id = _uuid(subject, "external_offer_id")
    cycle_id = _uuid(subject, "cycle_id")
    if external_offer_id is None or cycle_id is None:
        return None
    return {
        "cycle_id": str(cycle_id),
        "external_offer_id": str(external_offer_id),
        "expected_attached_cycle_id": str(cycle_id),
        "reason": "Consistency finding: the attachment does not match the cycle kind",
    }


def _deactivate_override(subject: Subject) -> dict[str, object] | None:
    override_id = _uuid(subject, "override_id")
    if override_id is None:
        return None
    return {
        "override_id": str(override_id),
        "reason": "Consistency finding: credited after its own expiry",
    }


def _update_job_basics(subject: Subject) -> dict[str, object] | None:
    # Deliberately not prefilled: the repair is a deadline the office has to
    # choose, and inventing one here would be the preview lying about what the
    # button does.
    del subject
    return None


def _re_extend_offer(subject: Subject) -> dict[str, object] | None:
    offer_id = _uuid(subject, "offer_id")
    cycle_id = _uuid(subject, "cycle_id")
    job_id = _uuid(subject, "job_id")
    application_id = _uuid(subject, "application_id")
    expected_status = subject.get("expected_status")
    if None in (offer_id, cycle_id, job_id, application_id) or expected_status is None:
        return None
    return {
        "cycle_id": str(cycle_id),
        "job_id": str(job_id),
        "application_id": str(application_id),
        "offer_id": str(offer_id),
        "expected_status": str(expected_status),
        "reason": "Consistency finding: re-offering after the auto-accept fallback",
    }


def _withdraw_duplicate(subject: Subject) -> dict[str, object] | None:
    application_id = _uuid(subject, "duplicate_application_id")
    cycle_id = _uuid(subject, "cycle_id")
    if application_id is None or cycle_id is None:
        return None
    return {
        "cycle_id": str(cycle_id),
        "application_id": str(application_id),
        "to_status": "withdrawn",
        "reason": "Consistency finding: closing the duplicate active application",
    }


def _set_default_resume(subject: Subject) -> dict[str, object] | None:
    # SPEC-GAP: PRO-3's default-resume commands belong to the student, and no
    # administrative equivalent exists.  The finding names the command that
    # repairs it and deliberately offers no button, rather than rendering one
    # that would be refused for the administrator who pressed it.
    del subject
    return None


def _contact_update(subject: Subject) -> dict[str, object] | None:
    contact_id = _uuid(subject, "contact_id")
    company_id = _uuid(subject, "company_id")
    if contact_id is None or company_id is None:
        return None
    # Re-asserting one contact as primary is what clears the others: the
    # single-primary flip drops the old marker first (M7).
    return {
        "company_id": str(company_id),
        "contact_id": str(contact_id),
        "is_primary": True,
    }


def _admin_update_profile(subject: Subject) -> dict[str, object] | None:
    # The roll clash needs a human to say which enrollment keeps the number.
    del subject
    return None


#: The auto-accept fallback finding M12's expiry worker already writes.  It is
#: not detected here -- the worker records it at the moment it happens -- but it
#: gets its fix from the same catalog so ``admin/findings`` treats every finding
#: alike (the design review section 4.29).
EXPIRY_FALLBACK_INVARIANT = "offer_expiry_auto_accept_gate_failed"


INVARIANTS: tuple[Invariant, ...] = (
    Invariant(
        id="application_status_matches_latest_event",
        description="An application's stored status is the one its latest event moved it to",
        sql="""
            SELECT a.id AS application_id, j.cycle_id, a.status AS stored_status,
                   last.to_status AS expected_status,
                   'Stored status ' || a.status || ' but the latest event moved it to '
                       || last.to_status AS detail
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            JOIN LATERAL (
                SELECT e.to_status
                FROM application_events e
                WHERE e.application_id = a.id AND e.to_status IS NOT NULL
                ORDER BY e.event_seq DESC
                LIMIT 1
            ) last ON true
            WHERE a.status <> last.to_status
        """,
        subject_columns=("application_id", "cycle_id", "stored_status", "expected_status"),
    ),
    Invariant(
        id="one_active_application_per_pair",
        description="A student holds at most one active application per job",
        sql="""
            SELECT a.job_id, j.cycle_id, a.enrollment_id,
                   min(a.id::text)::uuid AS application_id,
                   max(a.id::text)::uuid AS duplicate_application_id,
                   'This student holds ' || count(*)
                       || ' active applications to the same job' AS detail
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            WHERE a.status NOT IN ('withdrawn', 'auto_withdrawn')
            GROUP BY a.job_id, j.cycle_id, a.enrollment_id
            HAVING count(*) > 1
        """,
        subject_columns=(
            "job_id",
            "cycle_id",
            "enrollment_id",
            "application_id",
            "duplicate_application_id",
        ),
        db_backstopped=True,
    ),
    Invariant(
        id="one_current_enrollment_per_user",
        description="A user has at most one current enrollment",
        sql="""
            SELECT user_id, min(id::text)::uuid AS enrollment_id,
                   'This user has ' || count(*) || ' current enrollments' AS detail
            FROM enrollments WHERE is_current
            GROUP BY user_id HAVING count(*) > 1
        """,
        subject_columns=("user_id", "enrollment_id"),
        db_backstopped=True,
    ),
    Invariant(
        id="one_current_roll_number",
        description="A roll number belongs to at most one current enrollment",
        sql="""
            SELECT roll_number::text AS roll_number,
                   min(id::text)::uuid AS enrollment_id,
                   'Roll number ' || roll_number || ' is held by ' || count(*)
                       || ' current enrollments' AS detail
            FROM enrollments
            WHERE is_current AND roll_number IS NOT NULL
            GROUP BY roll_number HAVING count(*) > 1
        """,
        subject_columns=("roll_number", "enrollment_id"),
        db_backstopped=True,
    ),
    Invariant(
        id="one_default_resume_per_enrollment",
        description="An enrollment has at most one default resume",
        sql="""
            SELECT enrollment_id, min(id::text)::uuid AS resume_id,
                   'This student has ' || count(*) || ' default resumes' AS detail
            FROM resumes WHERE is_default
            GROUP BY enrollment_id HAVING count(*) > 1
        """,
        subject_columns=("enrollment_id", "resume_id"),
        db_backstopped=True,
    ),
    Invariant(
        id="one_primary_contact_per_company",
        description="A company has at most one primary contact",
        sql="""
            SELECT company_id, min(id::text)::uuid AS contact_id,
                   'This company has ' || count(*) || ' primary contacts' AS detail
            FROM company_contacts WHERE is_primary
            GROUP BY company_id HAVING count(*) > 1
        """,
        subject_columns=("company_id", "contact_id"),
        db_backstopped=True,
    ),
    Invariant(
        id="accepted_offers_within_cycle_cap",
        description="Accepted offers in a cycle stay within the cycle's cap where one is set",
        sql="""
            WITH portal_accepted AS (
                SELECT j.cycle_id, a.enrollment_id, o.id AS offer_id,
                       EXISTS (
                           SELECT 1
                           FROM application_events e
                           CROSS JOIN LATERAL jsonb_array_elements_text(
                               coalesce(e.payload -> 'applied_override_ids', '[]'::jsonb)
                           ) credit(override_id)
                           JOIN overrides credited
                             ON credited.id::text = credit.override_id
                           WHERE e.application_id = a.id
                             AND e.event_type = 'accepted'
                             AND e.payload ->> 'offer_id' = o.id::text
                             AND e.event_seq = (
                                 SELECT max(latest.event_seq)
                                 FROM application_events latest
                                 WHERE latest.application_id = a.id
                                   AND latest.event_type = 'accepted'
                                   AND latest.payload ->> 'offer_id' = o.id::text
                             )
                             AND credited.rule_domain = 'offer_cap'
                             AND credited.allow
                             AND credited.created_at <= e.created_at
                             AND (
                                 credited.expires_at IS NULL
                                 OR credited.expires_at > e.created_at
                             )
                       ) AS authorised
                FROM offers o
                JOIN applications a ON a.id = o.application_id
                JOIN jobs j ON j.id = a.job_id
                WHERE o.response = 'accepted' AND o.terminated_at IS NULL
            ),
            external_accepted AS (
                SELECT x.attached_cycle_id AS cycle_id, x.enrollment_id,
                       NULL::uuid AS offer_id,
                       (
                           EXISTS (
                               SELECT 1
                               FROM audit_log l
                               CROSS JOIN LATERAL jsonb_array_elements_text(
                                   coalesce(
                                       l.details -> 'applied_override_ids', '[]'::jsonb
                                   )
                               ) credit(override_id)
                               JOIN overrides credited
                                 ON credited.id::text = credit.override_id
                               WHERE l.action IN (
                                   'create_external_offer', 'update_external_offer'
                               )
                                 AND l.details ->> 'external_offer_id' = x.id::text
                                 AND coalesce(
                                     l.details ->> 'to_status',
                                     l.details ->> 'status'
                                 ) = 'accepted'
                                 AND l.audit_seq = (
                                     SELECT max(latest.audit_seq)
                                     FROM audit_log latest
                                     WHERE latest.action IN (
                                         'create_external_offer',
                                         'update_external_offer'
                                     )
                                       AND latest.details ->> 'external_offer_id'
                                           = x.id::text
                                       AND coalesce(
                                           latest.details ->> 'to_status',
                                           latest.details ->> 'status'
                                       ) = 'accepted'
                                 )
                                 AND credited.rule_domain = 'offer_cap'
                                 AND credited.allow
                                 AND credited.created_at <= l.created_at
                                 AND (
                                     credited.expires_at IS NULL
                                     OR credited.expires_at > l.created_at
                                 )
                           )
                           OR EXISTS (
                               SELECT 1
                               FROM audit_log l
                               CROSS JOIN LATERAL jsonb_array_elements_text(
                                   coalesce(
                                       l.details -> 'applied_override_ids', '[]'::jsonb
                                   )
                               ) credit(override_id)
                               JOIN overrides credited
                                 ON credited.id::text = credit.override_id
                               WHERE l.action IN (
                                   'attach_external_offer', 'attach_external_offers'
                               )
                                 AND l.details ->> 'external_offer_id' = x.id::text
                                 AND l.details ->> 'cycle_id'
                                     = x.attached_cycle_id::text
                                 AND l.audit_seq = (
                                     SELECT max(latest.audit_seq)
                                     FROM audit_log latest
                                     WHERE latest.action IN (
                                         'attach_external_offer',
                                         'attach_external_offers'
                                     )
                                       AND latest.details ->> 'external_offer_id'
                                           = x.id::text
                                       AND latest.details ->> 'cycle_id'
                                           = x.attached_cycle_id::text
                                 )
                                 AND credited.rule_domain = 'offer_cap'
                                 AND credited.allow
                                 AND credited.created_at <= l.created_at
                                 AND (
                                     credited.expires_at IS NULL
                                     OR credited.expires_at > l.created_at
                                 )
                           )
                       ) AS authorised
                FROM external_offers x
                WHERE x.status = 'accepted' AND x.attached_cycle_id IS NOT NULL
            ),
            accepted AS (
                SELECT * FROM portal_accepted
                UNION ALL
                SELECT * FROM external_accepted
            )
            SELECT grouped.cycle_id, grouped.enrollment_id, grouped.accepted_count,
                   grouped.cap, newest.offer_id, newest.application_id, newest.job_id,
                   newest.stored_status,
                   'This student holds ' || grouped.accepted_count
                       || ' accepted offers in a cycle capped at '
                       || grouped.cap AS detail
            FROM (
                SELECT accepted.cycle_id, accepted.enrollment_id,
                       count(*) AS accepted_count,
                       p.max_accepted_offers AS cap
                FROM accepted
                JOIN cycle_policies p ON p.cycle_id = accepted.cycle_id
                WHERE p.max_accepted_offers IS NOT NULL
                GROUP BY accepted.cycle_id, accepted.enrollment_id,
                         p.max_accepted_offers
                HAVING count(*) FILTER (WHERE NOT accepted.authorised)
                       > p.max_accepted_offers
            ) grouped
            LEFT JOIN LATERAL (
                SELECT o.id AS offer_id, a.id AS application_id, a.job_id,
                       a.status::text AS stored_status
                FROM offers o
                JOIN applications a ON a.id = o.application_id
                JOIN jobs j ON j.id = a.job_id
                WHERE o.response = 'accepted' AND o.terminated_at IS NULL
                  AND j.cycle_id = grouped.cycle_id
                  AND a.enrollment_id = grouped.enrollment_id
                ORDER BY o.extended_at DESC, o.id DESC
                LIMIT 1
            ) newest ON true
        """,
        subject_columns=(
            "cycle_id",
            "enrollment_id",
            "offer_id",
            "application_id",
            "job_id",
            "stored_status",
            "accepted_count",
            "cap",
        ),
    ),
    Invariant(
        id="one_accepted_placement_offer_globally",
        description=(
            "A student holds at most one accepted, unterminated placement offer "
            "across the whole portal"
        ),
        sql="""
            WITH portal_placements AS (
                SELECT a.enrollment_id, j.cycle_id, o.id AS offer_id,
                       EXISTS (
                           SELECT 1
                           FROM application_events e
                           CROSS JOIN LATERAL jsonb_array_elements_text(
                               coalesce(e.payload -> 'applied_override_ids', '[]'::jsonb)
                           ) credit(override_id)
                           JOIN overrides credited
                             ON credited.id::text = credit.override_id
                           WHERE e.application_id = a.id
                             AND e.event_type = 'accepted'
                             AND e.payload ->> 'offer_id' = o.id::text
                             AND e.event_seq = (
                                 SELECT max(latest.event_seq)
                                 FROM application_events latest
                                 WHERE latest.application_id = a.id
                                   AND latest.event_type = 'accepted'
                                   AND latest.payload ->> 'offer_id' = o.id::text
                             )
                             AND credited.rule_domain = 'outcome_gate'
                             AND credited.allow
                             AND credited.created_at <= e.created_at
                             AND (
                                 credited.expires_at IS NULL
                                 OR credited.expires_at > e.created_at
                             )
                       ) AS authorised
                FROM offers o
                JOIN applications a ON a.id = o.application_id
                JOIN jobs j ON j.id = a.job_id
                WHERE o.response = 'accepted' AND o.terminated_at IS NULL
                  AND j.outcome = 'placement'
            ),
            external_placements AS (
                SELECT x.enrollment_id, x.attached_cycle_id AS cycle_id,
                       NULL::uuid AS offer_id,
                       EXISTS (
                           SELECT 1
                           FROM audit_log l
                           CROSS JOIN LATERAL jsonb_array_elements_text(
                               coalesce(
                                   l.details -> 'applied_override_ids', '[]'::jsonb
                               )
                           ) credit(override_id)
                           JOIN overrides credited
                             ON credited.id::text = credit.override_id
                           WHERE l.action IN (
                               'create_external_offer', 'update_external_offer'
                           )
                             AND l.details ->> 'external_offer_id' = x.id::text
                             AND coalesce(
                                 l.details ->> 'to_status',
                                 l.details ->> 'status'
                             ) = 'accepted'
                             AND l.audit_seq = (
                                 SELECT max(latest.audit_seq)
                                 FROM audit_log latest
                                 WHERE latest.action IN (
                                     'create_external_offer',
                                     'update_external_offer'
                                 )
                                   AND latest.details ->> 'external_offer_id'
                                       = x.id::text
                                   AND coalesce(
                                       latest.details ->> 'to_status',
                                       latest.details ->> 'status'
                                   ) = 'accepted'
                             )
                             AND credited.rule_domain = 'outcome_gate'
                             AND credited.allow
                             AND credited.created_at <= l.created_at
                             AND (
                                 credited.expires_at IS NULL
                                 OR credited.expires_at > l.created_at
                             )
                       ) AS authorised
                FROM external_offers x
                WHERE x.status = 'accepted' AND x.outcome = 'placement'
            ),
            placements AS (
                SELECT * FROM portal_placements
                UNION ALL
                SELECT * FROM external_placements
            )
            SELECT grouped.enrollment_id, grouped.accepted_count,
                   newest.cycle_id, newest.offer_id, newest.application_id,
                   newest.job_id, newest.stored_status,
                   'This student holds ' || grouped.accepted_count
                       || ' accepted placement offers; DER-1 allows one' AS detail
            FROM (
                SELECT enrollment_id, count(*) AS accepted_count
                FROM placements
                GROUP BY enrollment_id
                HAVING count(*) FILTER (WHERE NOT placements.authorised) > 1
            ) grouped
            LEFT JOIN LATERAL (
                SELECT j.cycle_id, o.id AS offer_id, a.id AS application_id, a.job_id,
                       a.status::text AS stored_status
                FROM offers o
                JOIN applications a ON a.id = o.application_id
                JOIN jobs j ON j.id = a.job_id
                WHERE o.response = 'accepted' AND o.terminated_at IS NULL
                  AND j.outcome = 'placement'
                  AND a.enrollment_id = grouped.enrollment_id
                ORDER BY o.extended_at DESC, o.id DESC
                LIMIT 1
            ) newest ON true
        """,
        subject_columns=(
            "enrollment_id",
            "cycle_id",
            "offer_id",
            "application_id",
            "job_id",
            "stored_status",
            "accepted_count",
        ),
    ),
    Invariant(
        id="placement_derivation_matches_accepted_rows",
        description=(
            "An application marked accepted has an accepted, unterminated offer "
            "behind it"
        ),
        sql="""
            SELECT a.id AS application_id, j.cycle_id, a.status AS stored_status,
                   -- What the offer record says actually happened, so the
                   -- suggested force_transition realigns the stored status with
                   -- the evidence rather than with a guess.
                   CASE
                       WHEN latest.terminated_at IS NOT NULL THEN 'offer_terminated'
                       WHEN latest.response = 'declined' THEN 'declined'
                   END AS expected_status,
                   'This application is accepted but no accepted, unterminated '
                       || 'offer supports it, so every DER-1 derivation over it is wrong'
                       AS detail
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            LEFT JOIN LATERAL (
                SELECT o.response, o.terminated_at FROM offers o
                WHERE o.application_id = a.id
                ORDER BY o.extended_at DESC, o.id DESC LIMIT 1
            ) latest ON true
            WHERE a.status = 'accepted'
              AND NOT EXISTS (
                  SELECT 1 FROM offers o
                  WHERE o.application_id = a.id
                    AND o.response = 'accepted' AND o.terminated_at IS NULL
              )
        """,
        subject_columns=("application_id", "cycle_id", "stored_status", "expected_status"),
    ),
    Invariant(
        id="no_open_offer_on_unoffered_application",
        description=(
            "An unresponded, unterminated offer exists only on an application "
            "that is offered"
        ),
        sql="""
            SELECT o.id AS offer_id, a.id AS application_id, a.job_id, j.cycle_id,
                   a.status AS stored_status, 'offered'::text AS expected_status,
                   'An offer is still open on an application that is '
                       || a.status AS detail
            FROM offers o
            JOIN applications a ON a.id = o.application_id
            JOIN jobs j ON j.id = a.job_id
            WHERE o.response IS NULL AND o.terminated_at IS NULL
              AND a.status <> 'offered'
        """,
        subject_columns=(
            "offer_id",
            "application_id",
            "job_id",
            "cycle_id",
            "stored_status",
            "expected_status",
        ),
    ),
    Invariant(
        id="converted_penalties_keep_their_strikes",
        description=(
            "A penalty converted from strikes is supported by at least the "
            "global threshold of consumed strikes"
        ),
        sql="""
            SELECT p.id AS penalty_id, p.enrollment_id,
                   count(s.id) AS supporting_strikes,
                   (SELECT (value #>> '{}')::int FROM settings
                    WHERE key = 'strikes_per_penalty') AS threshold,
                   'This converted penalty is supported by ' || count(s.id)
                       || ' active strikes' AS detail
            FROM penalties p
            LEFT JOIN strikes s
                ON s.consumed_by_penalty_id = p.id AND s.is_active
            WHERE p.from_strikes AND p.is_active
              AND (SELECT (value #>> '{}')::int FROM settings
                   WHERE key = 'strikes_per_penalty') IS NOT NULL
            GROUP BY p.id, p.enrollment_id
            HAVING count(s.id) < (SELECT (value #>> '{}')::int FROM settings
                                  WHERE key = 'strikes_per_penalty')
        """,
        subject_columns=("penalty_id", "enrollment_id", "supporting_strikes", "threshold"),
    ),
    Invariant(
        id="no_live_application_without_active_membership",
        description="A live application belongs to an active cycle membership",
        sql="""
            SELECT a.id AS application_id, j.cycle_id, a.enrollment_id,
                   m.id AS membership_id,
                   coalesce(m.status::text, 'absent') AS membership_status,
                   'This application is ' || a.status || ' but the membership is '
                       || coalesce(m.status::text, 'missing') AS detail
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            LEFT JOIN cycle_memberships m
                ON m.cycle_id = j.cycle_id AND m.enrollment_id = a.enrollment_id
            WHERE a.status IN ('in_progress', 'pending_offer', 'offered')
              AND (m.id IS NULL OR m.status <> 'active')
        """,
        subject_columns=(
            "application_id",
            "cycle_id",
            "enrollment_id",
            "membership_id",
            "membership_status",
        ),
    ),
    Invariant(
        id="round_states_exist_up_to_current_round",
        description=(
            "A live application has a round state for every round up to the one "
            "it is sitting in, and none beyond it"
        ),
        sql="""
            WITH live AS (
                SELECT a.id AS application_id, a.job_id, a.current_round_id,
                       j.cycle_id, r.ord AS current_ord
                FROM applications a
                JOIN jobs j ON j.id = a.job_id
                JOIN job_rounds r ON r.id = a.current_round_id
                WHERE a.status = 'in_progress'
            )
            SELECT live.application_id, live.cycle_id, live.current_round_id,
                   count(*) FILTER (WHERE s.id IS NULL) AS missing_states,
                   count(*) FILTER (WHERE s.id IS NOT NULL AND r.ord > live.current_ord)
                       AS extra_states,
                   'The round-state ledger does not match the round this '
                       || 'application is sitting in' AS detail
            FROM live
            JOIN job_rounds r ON r.job_id = live.job_id
            LEFT JOIN application_round_states s
                ON s.application_id = live.application_id AND s.round_id = r.id
            WHERE (r.ord <= live.current_ord AND s.id IS NULL)
               OR (r.ord > live.current_ord AND s.id IS NOT NULL)
            GROUP BY live.application_id, live.cycle_id, live.current_round_id
        """,
        subject_columns=(
            "application_id",
            "cycle_id",
            "current_round_id",
            "missing_states",
            "extra_states",
        ),
    ),
    Invariant(
        id="external_attachments_match_cycle_kind",
        description="An external offer is attached only to a cycle of its own kind",
        sql="""
            SELECT x.id AS external_offer_id, x.attached_cycle_id AS cycle_id,
                   x.enrollment_id, x.outcome::text AS outcome, c.kind::text AS cycle_kind,
                   'A ' || x.outcome || ' offer is attached to a ' || c.kind
                       || ' cycle' AS detail
            FROM external_offers x
            JOIN cycles c ON c.id = x.attached_cycle_id
            WHERE (c.kind = 'placement' AND x.outcome <> 'placement')
               OR (c.kind = 'internship' AND x.outcome <> 'internship')
        """,
        subject_columns=(
            "external_offer_id",
            "cycle_id",
            "enrollment_id",
            "outcome",
            "cycle_kind",
        ),
    ),
    Invariant(
        id="dedicated_cycle_jobs_carry_an_application_deadline",
        description="Only an open-cycle job may have no application deadline",
        sql="""
            SELECT j.id AS job_id, j.cycle_id, c.kind::text AS cycle_kind,
                   'This job carries no application deadline, which only an '
                       || 'open cycle allows' AS detail
            FROM jobs j JOIN cycles c ON c.id = j.cycle_id
            WHERE j.application_deadline IS NULL AND c.kind <> 'open'
        """,
        subject_columns=("job_id", "cycle_id", "cycle_kind"),
    ),
    Invariant(
        id="open_cycle_jobs_carry_no_acceptance_deadline",
        description="An open-cycle job has no offer-acceptance deadline",
        sql="""
            SELECT j.id AS job_id, j.cycle_id, c.kind::text AS cycle_kind,
                   'This open-cycle job carries an offer-acceptance deadline, but '
                       || 'open cycles record outcomes directly' AS detail
            FROM jobs j JOIN cycles c ON c.id = j.cycle_id
            WHERE j.offer_acceptance_deadline IS NOT NULL AND c.kind = 'open'
        """,
        subject_columns=("job_id", "cycle_id", "cycle_kind"),
    ),
    Invariant(
        id="no_override_credited_after_expiry",
        description="No decision credits an override after that override expired",
        sql="""
            SELECT o.id AS override_id, e.application_id, j.cycle_id,
                   e.id AS event_id,
                   'Override ' || o.id || ' was credited by an event recorded after '
                       || 'its expiry' AS detail
            FROM application_events e
            JOIN applications a ON a.id = e.application_id
            JOIN jobs j ON j.id = a.job_id
            JOIN overrides o
                ON o.id::text = ANY (
                    SELECT jsonb_array_elements_text(e.payload -> 'applied_override_ids')
                )
            WHERE o.expires_at IS NOT NULL AND e.created_at > o.expires_at
        """,
        subject_columns=("override_id", "application_id", "cycle_id", "event_id"),
    ),
)


FIX_CATALOG: Mapping[str, SuggestedFix] = {
    "application_status_matches_latest_event": SuggestedFix(
        "force_transition", _force_transition
    ),
    "one_active_application_per_pair": SuggestedFix(
        "force_transition", _withdraw_duplicate
    ),
    # A second current enrollment is IDN-2's own invariant and no command flips
    # is_current directly; start_new_enrollment only ever creates the newest one.
    # SPEC-GAP: no sanctioned command demotes an enrollment, so this finding
    # names the state and waits for a human rather than pointing at a command
    # that cannot do it.
    "one_current_enrollment_per_user": SuggestedFix(
        "start_new_enrollment", lambda _subject: None
    ),
    "one_current_roll_number": SuggestedFix("admin_update_profile", _admin_update_profile),
    "one_default_resume_per_enrollment": SuggestedFix(
        "set_default_resume", _set_default_resume
    ),
    "one_primary_contact_per_company": SuggestedFix("contact_update", _contact_update),
    "accepted_offers_within_cycle_cap": SuggestedFix("terminate_offer", _terminate_offer),
    "one_accepted_placement_offer_globally": SuggestedFix(
        "terminate_offer", _terminate_offer
    ),
    "placement_derivation_matches_accepted_rows": SuggestedFix(
        "force_transition", _force_transition
    ),
    # Realign the application with the offer record first: terminate_offer
    # itself only acts on an offered or accepted application (OFR-5), so the
    # repair that unblocks every other one is the status move.
    "no_open_offer_on_unoffered_application": SuggestedFix(
        "force_transition", _force_transition
    ),
    "converted_penalties_keep_their_strikes": SuggestedFix(
        "revoke_penalty", _revoke_penalty
    ),
    "no_live_application_without_active_membership": SuggestedFix(
        "restore_membership", _restore_membership
    ),
    "round_states_exist_up_to_current_round": SuggestedFix(
        "reinstate_application", _reinstate
    ),
    "external_attachments_match_cycle_kind": SuggestedFix(
        "detach_external_offer", _detach_external
    ),
    "dedicated_cycle_jobs_carry_an_application_deadline": SuggestedFix(
        "update_job_basics", _update_job_basics
    ),
    "open_cycle_jobs_carry_no_acceptance_deadline": SuggestedFix(
        "update_job_basics", _update_job_basics
    ),
    "no_override_credited_after_expiry": SuggestedFix(
        "deactivate_override", _deactivate_override
    ),
    EXPIRY_FALLBACK_INVARIANT: SuggestedFix("re_extend_offer", _re_extend_offer),
}


def finding_id(invariant: str, subject: Subject) -> UUID:
    """The stable identity of one finding, so a nightly re-run never duplicates it."""
    canonical = ";".join(f"{key}={subject[key]!s}" for key in sorted(subject))
    return uuid5(NAMESPACE_URL, f"cds:finding:{invariant}:{canonical}")


def describe(invariant_id: str) -> str:
    """The human description of one invariant, including the worker's own."""
    for invariant in INVARIANTS:
        if invariant.id == invariant_id:
            return invariant.description
    if invariant_id == EXPIRY_FALLBACK_INVARIANT:
        return "An auto-accepting offer fell back to declining because a gate failed"
    return invariant_id.replace("_", " ")


def suggested_fix_for(invariant_id: str) -> SuggestedFix | None:
    return FIX_CATALOG.get(invariant_id)


def fix_payload(invariant_id: str, subject: Subject) -> dict[str, object] | None:
    """What the admin screen's one-click button sends, or None when it has no button."""
    fix = suggested_fix_for(invariant_id)
    if fix is None:
        return None
    built = fix.build_input(subject)
    return (
        {"command": fix.command, "input": built}
        if built is not None
        else {"command": fix.command, "input": None}
    )


def subject_of(invariant: Invariant, row: sa.RowMapping) -> Subject:
    """Project one violation row onto the subject refs the finding carries."""
    return {
        column: (str(row[column]) if isinstance(row[column], UUID) else row[column])
        for column in invariant.subject_columns
        if row.get(column) is not None
    }


def detail_of(row: sa.RowMapping) -> str:
    return str(cast(object, row["detail"]))
