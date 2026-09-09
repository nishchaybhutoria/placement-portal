"""Job screens for staff and students (LLD section 11.3, Behavior JOB-4).

The student-facing half is the one that matters most.  JOB-4 says a student
sees every published job in a cycle they are active in -- eligible or not --
with "the exact failing reasons" on the ones they cannot apply to.  So a card
carries the full list, standing gates and rule leaves together, computed here
by the same ``evaluate_gates`` and ``evaluate`` that will bind at apply time.
Showing a student one reason, or a vague one, would leave them fixing the wrong
thing.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from decimal import Decimal
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from app.core.plan import ScopeIds
from app.domain.rules import NO_RULE_SUMMARY, profile_taxonomy_ids, taxonomy_ids
from app.domain.shared import CycleKind, domains_for_scope
from app.modules.applications.verdict import (
    compute_verdict,
    load_cycle_header,
    load_gate_overrides,
    load_rule_labels,
    load_student_context,
    student_job_query,
)
from app.modules.jobs.cancel import cancellation_targets
from app.modules.jobs.commands import JOB_COLUMNS
from app.modules.jobs.eligibility import (
    MEMBER_PROFILE_SELECT,
    evaluate_members,
    member_profiles_with_placement,
)
from app.modules.offers.derivations import placement_placed_enrollments
from app.modules.overrides.service import ClassifiedOverride, classified_many
from app.modules.taxonomies.labels import resolve_labels

_JOB_SELECT = ", ".join(f"j.{column.strip()}" for column in JOB_COLUMNS.split(","))
_JOB_LIST = f"""
    SELECT {_JOB_SELECT},
        c.name AS company_name,
        s.name AS sector_name,
        (SELECT count(*) FROM job_rounds r WHERE r.job_id = j.id) AS round_count,
        (SELECT count(*) FROM job_questions q WHERE q.job_id = j.id) AS question_count,
        (
            SELECT count(*) FROM applications a
            WHERE a.job_id = j.id
              AND a.status NOT IN ('withdrawn', 'auto_withdrawn')
        ) AS application_count
    FROM jobs j
    JOIN companies c ON c.id = j.company_id
    LEFT JOIN sectors s ON s.id = j.sector_id
    WHERE {{filter}}
    ORDER BY j.is_published DESC, c.name, j.title, j.id
"""
_CYCLE_JOBS = _JOB_LIST.format(filter="j.cycle_id = :cycle_id")
_ONE_JOB = _JOB_LIST.format(filter="j.id = :job_id AND j.cycle_id = :cycle_id")


def _money(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _override_payload(row: ClassifiedOverride) -> dict[str, object]:
    return {
        "id": str(row.id),
        "rule_domain": row.rule_domain.value,
        "allow": row.allow,
        "scope": row.specificity,
        "state": row.state,
        "reason": row.reason,
        "expires_at": _iso(row.expires_at),
        "subject_label": None,
    }


def _job_payload(row: sa.RowMapping) -> dict[str, object]:
    return {
        "id": str(cast(UUID, row["id"])),
        "cycle_id": str(cast(UUID, row["cycle_id"])),
        "company": {
            "id": str(cast(UUID, row["company_id"])),
            "name": str(row["company_name"]),
        },
        "outcome": str(row["outcome"]),
        "title": str(row["title"]),
        "description": str(row["description"]),
        "location": row["location"],
        "sector": row["sector_name"],
        "sector_id": str(cast(UUID, row["sector_id"])) if row["sector_id"] else None,
        "ctc_lpa": _money(row["ctc_lpa"]),
        "ctc_breakdown": row["ctc_breakdown"],
        "stipend_month": _money(row["stipend_month"]),
        "application_deadline": _iso(row["application_deadline"]),
        "offer_acceptance_deadline": _iso(row["offer_acceptance_deadline"]),
        "is_published": bool(row["is_published"]),
        "published_at": _iso(row["published_at"]),
        "cancelled_at": _iso(row["cancelled_at"]),
        "eligibility_summary": row["eligibility_summary"] or NO_RULE_SUMMARY,
    }


async def _cycle_header(
    connection: AsyncConnection, cycle_id: UUID
) -> sa.RowMapping | None:
    """The cycle row every screen here judges against.

    Shared with ``apply`` (``applications/verdict.py``): the policy columns it
    carries are gate inputs, so both paths read them from one query.
    """
    return await load_cycle_header(connection, cycle_id)


async def staff_cycle_jobs(
    engine: AsyncEngine, cycle_id: UUID, *, include_cancelled: bool = True
) -> dict[str, object] | None:
    """Every job in one cycle with the counts staff triage from (JOB-2)."""
    async with engine.connect() as connection:
        cycle = await _cycle_header(connection, cycle_id)
        if cycle is None:
            return None
        rows = (
            await connection.execute(sa.text(_CYCLE_JOBS), {"cycle_id": cycle_id})
        ).mappings().all()
    return {
        "cycle": {
            "id": str(cast(UUID, cycle["id"])),
            "name": str(cycle["name"]),
            "kind": str(cycle["kind"]),
            "archived_at": _iso(cycle["archived_at"]),
        },
        "filters": {"include_cancelled": include_cancelled},
        "jobs": [
            _job_payload(row)
            | {
                "round_count": int(row["round_count"]),
                "question_count": int(row["question_count"]),
                "application_count": int(row["application_count"]),
            }
            for row in rows
            if include_cancelled or row["cancelled_at"] is None
        ],
    }


async def _job_rounds(connection: AsyncConnection, job_id: UUID) -> list[dict[str, object]]:
    rows = (
        await connection.execute(
            sa.text(
                "SELECT r.id, r.round_type_id, t.name AS round_type, r.name, r.ord, "
                "r.venue, r.scheduled_at, r.duration_min, r.instructions, "
                "EXISTS (SELECT 1 FROM application_round_states s "
                "WHERE s.round_id = r.id) AS has_round_state "
                "FROM job_rounds r JOIN round_types t ON t.id = r.round_type_id "
                "WHERE r.job_id = :job_id ORDER BY r.ord"
            ),
            {"job_id": job_id},
        )
    ).mappings().all()
    return [
        {
            "round_id": str(cast(UUID, row["id"])),
            "round_type_id": str(cast(UUID, row["round_type_id"])),
            "round_type": str(row["round_type"]),
            "name": str(row["name"]),
            "ord": int(row["ord"]),
            "venue": row["venue"],
            "scheduled_at": _iso(row["scheduled_at"]),
            "duration_min": row["duration_min"],
            "instructions": row["instructions"],
            # The builder greys out delete rather than letting staff discover
            # the JOB-3 lock only when the save is rejected.
            "deletable": not bool(row["has_round_state"]),
        }
        for row in rows
    ]


async def _job_questions(
    connection: AsyncConnection, job_id: UUID
) -> list[dict[str, object]]:
    rows = (
        await connection.execute(
            sa.text(
                "SELECT q.id, q.text, q.qtype, q.required, q.ord, "
                "(SELECT count(*) FROM application_answers a "
                "WHERE a.question_id = q.id) AS answer_count, "
                "coalesce((SELECT array_agg(o.text ORDER BY o.ord) "
                "FROM job_question_options o WHERE o.question_id = q.id), "
                "'{}') AS options "
                "FROM job_questions q WHERE q.job_id = :job_id ORDER BY q.ord"
            ),
            {"job_id": job_id},
        )
    ).mappings().all()
    return [
        {
            "question_id": str(cast(UUID, row["id"])),
            "text": str(row["text"]),
            "qtype": str(row["qtype"]),
            "required": bool(row["required"]),
            "ord": int(row["ord"]),
            "options": [str(option) for option in row["options"]],
            "answer_count": int(row["answer_count"]),
            "removable": not int(row["answer_count"]),
            "retypable": not int(row["answer_count"]),
        }
        for row in rows
    ]


async def _program_ctc(connection: AsyncConnection, job_id: UUID) -> list[dict[str, object]]:
    rows = (
        await connection.execute(
            sa.text(
                "SELECT jc.program_id, p.name, jc.ctc_lpa FROM job_program_ctc jc "
                "JOIN programs p ON p.id = jc.program_id "
                "WHERE jc.job_id = :job_id ORDER BY p.name"
            ),
            {"job_id": job_id},
        )
    ).mappings().all()
    return [
        {
            "program_id": str(cast(UUID, row["program_id"])),
            "program": str(row["name"]),
            "ctc_lpa": _money(row["ctc_lpa"]),
        }
        for row in rows
    ]


async def _fetch_job(
    connection: AsyncConnection, *, cycle_id: UUID, job_id: UUID
) -> sa.RowMapping | None:
    return (
        await connection.execute(
            sa.text(_ONE_JOB),
            {"cycle_id": cycle_id, "job_id": job_id},
        )
    ).mappings().one_or_none()


async def staff_job_builder(
    engine: AsyncEngine, *, cycle_id: UUID, job_id: UUID
) -> dict[str, object] | None:
    """All four builder tabs plus the live impact preview (JOB-2)."""
    async with engine.connect() as connection:
        cycle = await _cycle_header(connection, cycle_id)
        if cycle is None:
            return None
        job = await _fetch_job(connection, cycle_id=cycle_id, job_id=job_id)
        if job is None:
            return None
        rule = cast("dict[str, object] | None", job["eligibility_rule"])
        members = (
            await connection.execute(
                sa.text(_ACTIVE_MEMBERS_FOR_PREVIEW), {"cycle_id": cycle_id}
            )
        ).mappings().all()
        placed = await placement_placed_enrollments(
            connection,
            tuple(cast(UUID, row["enrollment_id"]) for row in members),
        )
        previewed = member_profiles_with_placement(members, placed)
        # The members' own taxonomy ids join the rule's, because a shortfall
        # names the value the student holds as well as the one the rule wants.
        labels = await resolve_labels(
            connection,
            taxonomy_ids(rule).union(
                *(profile_taxonomy_ids(profile) for profile in previewed)
            ),
        )
        verdicts = evaluate_members(rule, previewed, labels)
        targets, untouched = await cancellation_targets(connection, job_id)
        payload = _job_payload(job) | {
            "rounds": await _job_rounds(connection, job_id),
            "questions": await _job_questions(connection, job_id),
            "program_ctc": await _program_ctc(connection, job_id),
        }
        subject_overrides = await classified_many(
            connection,
            domains_for_scope("job"),
            (
                ScopeIds(cycle_id=cycle_id, job_id=job_id),
            ),
        )

    eligible = [verdict for verdict in verdicts if verdict.eligible]
    return {
        "cycle": {
            "id": str(cast(UUID, cycle["id"])),
            "name": str(cycle["name"]),
            "kind": str(cycle["kind"]),
            "archived_at": _iso(cycle["archived_at"]),
            # JOB-6: an open cycle's jobs have no rounds tab and no acceptance
            # deadline, so the builder is told rather than left to infer it.
            "supports_rounds": str(cycle["kind"]) != CycleKind.OPEN.value,
            "supports_offer_deadline": str(cycle["kind"]) != CycleKind.OPEN.value,
            "outcome_is_fixed": str(cycle["kind"]) != CycleKind.OPEN.value,
        },
        "job": payload,
        "override_domains": [domain.value for domain in domains_for_scope("job")],
        "overrides": [_override_payload(row) for row in subject_overrides],
        "eligibility": {
            "rule": rule,
            "summary": job["eligibility_summary"] or NO_RULE_SUMMARY,
            "impact": {
                "eligible_count": len(eligible),
                "member_count": len(verdicts),
                "members": [
                    {
                        "enrollment_id": str(verdict.enrollment_id),
                        "full_name": verdict.full_name,
                        "roll_number": verdict.roll_number,
                        "eligible": verdict.eligible,
                        "reasons": [asdict(reason) for reason in verdict.reasons],
                    }
                    for verdict in verdicts
                ],
            },
        },
        "cancellation_preview": {"targets": targets, "untouched": untouched},
    }


_ACTIVE_MEMBERS_FOR_PREVIEW = f"""
    SELECT
        e.id AS enrollment_id, e.roll_number, u.full_name, u.email,
        {MEMBER_PROFILE_SELECT}
    FROM cycle_memberships m
    JOIN enrollments e ON e.id = m.enrollment_id
    JOIN users u ON u.id = e.user_id
    LEFT JOIN profiles p ON p.enrollment_id = e.id
    WHERE m.cycle_id = :cycle_id AND m.status = 'active'
    ORDER BY u.full_name, e.id
"""

_STUDENT_CYCLE_JOBS = student_job_query("j.cycle_id = :cycle_id")
_STUDENT_ONE_JOB = student_job_query("j.id = :job_id")


async def student_cycle_jobs(
    engine: AsyncEngine, *, cycle_id: UUID, enrollment_id: UUID
) -> dict[str, object] | None:
    """Every published job in the cycle, each with its full verdict (JOB-4)."""
    async with engine.connect() as connection:
        cycle = await _cycle_header(connection, cycle_id)
        if cycle is None:
            return None
        rows = (
            await connection.execute(
                sa.text(_STUDENT_CYCLE_JOBS),
                {"cycle_id": cycle_id, "enrollment_id": enrollment_id},
            )
        ).mappings().all()
        context = await load_student_context(
            connection, cycle=cycle, enrollment_id=enrollment_id, lock=False
        )
        labels = await load_rule_labels(
            connection,
            context,
            [cast("dict[str, object] | None", row["eligibility_rule"]) for row in rows],
        )
        # Overrides resolve per job because a job-scoped override outranks a
        # cycle-scoped one (INT-2 specificity), and a card that ignored them
        # would tell a student they are barred from a job staff have already
        # let them into.  One query per job on a screen showing a cycle's jobs.
        overrides = {
            cast(UUID, row["id"]): await load_gate_overrides(
                connection,
                scope_ids=ScopeIds(
                    cycle_id=cycle_id,
                    job_id=cast(UUID, row["id"]),
                    enrollment_id=enrollment_id,
                ),
            )
            for row in rows
        }

    cards: list[dict[str, object]] = []
    for row in rows:
        verdict = compute_verdict(
            context, row, labels=labels, overrides=overrides[cast(UUID, row["id"])]
        )
        eligible, reasons = verdict.eligible, [asdict(reason) for reason in verdict.reasons]
        cards.append(
            _job_payload(row)
            | {
                "round_count": int(row["round_count"]),
                "question_count": int(row["question_count"]),
                "eligible": eligible,
                "reasons": reasons,
                "application": (
                    {
                        "application_id": str(cast(UUID, row["application_id"])),
                        "status": str(row["application_status"]),
                    }
                    if row["application_id"] is not None
                    else None
                ),
            }
        )
    return {
        "cycle": {
            "id": str(cast(UUID, cycle["id"])),
            "name": str(cycle["name"]),
            "kind": str(cycle["kind"]),
            "archived_at": _iso(cycle["archived_at"]),
        },
        "membership_status": context.membership_status.value,
        "eligible_count": sum(1 for card in cards if card["eligible"]),
        "jobs": cards,
    }


async def student_job_detail(
    engine: AsyncEngine, *, job_id: UUID, enrollment_id: UUID
) -> dict[str, object] | None:
    """One job in full: comp for this student's program, rounds, form (JOB-4)."""
    async with engine.connect() as connection:
        located = (
            await connection.execute(
                sa.text("SELECT cycle_id FROM jobs WHERE id = :id AND is_published"),
                {"id": job_id},
            )
        ).scalar_one_or_none()
        if located is None:
            return None
        cycle_id = cast(UUID, located)
        cycle = await _cycle_header(connection, cycle_id)
        if cycle is None:
            return None
        row = (
            await connection.execute(
                sa.text(_STUDENT_ONE_JOB),
                {"job_id": job_id, "enrollment_id": enrollment_id},
            )
        ).mappings().one_or_none()
        if row is None:
            return None
        context = await load_student_context(
            connection, cycle=cycle, enrollment_id=enrollment_id, lock=False
        )
        rule = cast("dict[str, object] | None", row["eligibility_rule"])
        labels = await load_rule_labels(connection, context, [rule])
        overrides = await load_gate_overrides(
            connection,
            scope_ids=ScopeIds(
                cycle_id=cycle_id, job_id=job_id, enrollment_id=enrollment_id
            ),
        )
        rounds = await _job_rounds(connection, job_id)
        questions = await _job_questions(connection, job_id)
        program_ctc = await _program_ctc(connection, job_id)
        resumes = (
            await connection.execute(
                sa.text(
                    "SELECT r.id, r.label, r.drive_url, r.is_default, "
                    "(m.default_resume_id = r.id) AS is_cycle_default "
                    "FROM resumes r LEFT JOIN cycle_memberships m "
                    "ON m.enrollment_id = r.enrollment_id AND m.cycle_id = :cycle_id "
                    "WHERE r.enrollment_id = :enrollment_id ORDER BY r.created_at, r.id"
                ),
                {"cycle_id": cycle_id, "enrollment_id": enrollment_id},
            )
        ).mappings().all()

    profile = context.profile
    verdict = compute_verdict(context, row, labels=labels, overrides=overrides)
    eligible = verdict.eligible
    reasons = [asdict(reason) for reason in verdict.reasons]
    # JOB-2.1: a per-program CTC row overrides the job's headline figure for
    # the students it names, so the student sees their own number, not both.
    program_id = profile.get("program_id")
    applicable_ctc = next(
        (
            entry
            for entry in program_ctc
            if program_id is not None and entry["program_id"] == str(program_id)
        ),
        None,
    )
    return {
        "enrollment_id": str(enrollment_id),
        "cycle": {
            "id": str(cast(UUID, cycle["id"])),
            "name": str(cycle["name"]),
            "kind": str(cycle["kind"]),
        },
        "job": _job_payload(row),
        "compensation": {
            "ctc_lpa": applicable_ctc["ctc_lpa"] if applicable_ctc else _money(row["ctc_lpa"]),
            "source": "program" if applicable_ctc else "job",
            "ctc_breakdown": row["ctc_breakdown"],
            "stipend_month": _money(row["stipend_month"]),
        },
        "eligibility": {
            "eligible": eligible,
            "summary": row["eligibility_summary"] or NO_RULE_SUMMARY,
            "reasons": reasons,
        },
        # JOB-6 lightweight jobs have no rounds; the key stays present and empty
        # so the client renders one shape.
        "rounds": [
            {key: value for key, value in round_.items() if key != "deletable"}
            for round_ in rounds
        ],
        "apply_form": {
            "questions": [
                {
                    key: value
                    for key, value in question.items()
                    if key not in {"answer_count", "removable", "retypable"}
                }
                for question in questions
            ],
            "resumes": [
                {
                    "id": str(cast(UUID, resume["id"])),
                    "label": str(resume["label"]),
                    "drive_url": str(resume["drive_url"]),
                    "is_default": bool(resume["is_default"]),
                    "is_cycle_default": bool(resume["is_cycle_default"]),
                }
                for resume in resumes
            ],
        },
        "application": (
            {
                "application_id": str(cast(UUID, row["application_id"])),
                "status": str(row["application_status"]),
            }
            if row["application_id"] is not None
            else None
        ),
    }
