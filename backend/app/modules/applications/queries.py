"""The student's own applications (LLD section 11.3, Behavior APP-3).

One screen answering "where do I stand, and what can I still do about it".  The
last part is why the window is computed here rather than left to the client: a
student looking at an application whose deadline passed last night must not be
shown an Edit button that the server will refuse, and the frontend cannot work
that out from a deadline alone -- it depends on two cycle policy flags and on
any override granted to this application.  So the screen reports what the
command would decide, from the same evaluator the command uses.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.errors import CYCLE_ARCHIVED
from app.core.plan import Reason, ScopeIds
from app.domain.gates import evaluate_edit_window, evaluate_withdraw_window
from app.domain.policy import resolve_policy
from app.domain.shared import ApplicationStatus, CycleKind, RuleDomain
from app.modules.analytics.columns import application_registry
from app.modules.applications.attendance import plan_attendance
from app.modules.applications.finalization import round_finalization_blocker
from app.modules.applications.rounds import (
    BoardRow,
    JobRound,
    Operation,
    board_rows,
    plan_row,
    round_state_rows,
)
from app.modules.applications.venues import slot_blocker
from app.modules.applications.verdict import gate_overrides
from app.modules.cycles.commands import POLICY_COLUMNS
from app.modules.overrides.service import applicable

_APPLICATIONS = f"""
    SELECT
        a.id, a.status, a.current_round_id, a.resume_url, a.applied_at,
        j.id AS job_id, j.title, j.application_deadline, j.outcome,
        j.cancelled_at,
        co.name AS company_name,
        c.id AS cycle_id, c.name AS cycle_name, c.kind AS cycle_kind,
        c.archived_at,
        r.name AS round_name, r.ord AS round_ord,
        (SELECT count(*) FROM job_rounds jr WHERE jr.job_id = j.id) AS round_count,
        (SELECT count(*) FROM application_answers ans
          WHERE ans.application_id = a.id) AS answer_count,
        {", ".join("cp." + column for column in POLICY_COLUMNS)}
    FROM applications a
    JOIN jobs j ON j.id = a.job_id
    JOIN companies co ON co.id = j.company_id
    JOIN cycles c ON c.id = j.cycle_id
    LEFT JOIN cycle_policies cp ON cp.cycle_id = c.id
    LEFT JOIN job_rounds r ON r.id = a.current_round_id
    WHERE a.enrollment_id = :enrollment_id
    ORDER BY a.applied_at DESC, a.id
"""

_TIMELINE = """
    SELECT application_id, event_type, from_status, to_status, reason, created_at
    FROM application_events
    WHERE application_id = ANY(:ids)
    ORDER BY event_seq
"""

_EDIT_QUESTIONS = """
    SELECT q.id, q.job_id, q.text, q.qtype, q.required, q.ord,
           o.id AS option_id, o.text AS option_text, o.ord AS option_ord
    FROM job_questions q
    LEFT JOIN job_question_options o ON o.question_id = q.id
    WHERE q.job_id = ANY(:job_ids)
    ORDER BY q.job_id, q.ord, o.ord
"""

_EDIT_ANSWERS = """
    SELECT application_id, question_id, value
    FROM application_answers
    WHERE application_id = ANY(:ids)
    ORDER BY application_id, question_id
"""

#: The statuses a student can still act on themselves (APP-3).  Everything else
#: is staff's to move, so the screen offers nothing.
_LIVE = frozenset({ApplicationStatus.IN_PROGRESS})


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _window(
    session: AsyncSession,
    row: sa.RowMapping,
    *,
    enrollment_id: UUID,
    now: datetime,
) -> tuple[bool, bool, list[dict[str, object]]]:
    """Can this student still edit or withdraw, and if not, why not?

    Edit and withdrawal read different policy flags (CYC-2 lists them
    separately), so a cycle can let a student pull out after the deadline while
    freezing what a live application says.
    """
    if ApplicationStatus(row["status"]) not in _LIVE or row["archived_at"] is not None:
        return False, False, []
    policy = resolve_policy(
        CycleKind(row["cycle_kind"]),
        cycle_policy={column: row[column] for column in POLICY_COLUMNS},
    )
    overrides = gate_overrides(
        await applicable(
            session,
            (RuleDomain.EDIT_WINDOW, RuleDomain.WITHDRAW_WINDOW),
            ScopeIds(
                cycle_id=cast(UUID, row["cycle_id"]),
                job_id=cast(UUID, row["job_id"]),
                enrollment_id=enrollment_id,
                application_id=cast(UUID, row["id"]),
            ),
        )
    )
    edit = evaluate_edit_window(
        now=now,
        deadline=row["application_deadline"],
        allowed_after_deadline=policy.allow_edit_after_deadline.value,
        overrides=overrides,
    )
    withdraw = evaluate_withdraw_window(
        now=now,
        deadline=row["application_deadline"],
        allowed_after_deadline=policy.allow_withdrawal_after_deadline.value,
        overrides=overrides,
    )
    # Both halves closing for the same reason is the common case; reporting it
    # once keeps the card from saying the same sentence twice.
    reasons = [asdict(reason) for reason in (edit.failures or withdraw.failures)]
    return edit.verdict, withdraw.verdict, reasons


async def me_applications(engine: AsyncEngine, enrollment_id: UUID) -> dict[str, object]:
    """Every application this enrollment has ever filed, newest first."""
    async with engine.connect() as connection:
        rows = (
            (await connection.execute(sa.text(_APPLICATIONS), {"enrollment_id": enrollment_id}))
            .mappings()
            .all()
        )
        now = cast(datetime, await connection.scalar(sa.select(sa.func.now())))
        application_ids = [row["id"] for row in rows]
        job_ids = sorted({row["job_id"] for row in rows})
        timeline = (
            (await connection.execute(sa.text(_TIMELINE), {"ids": application_ids}))
            .mappings()
            .all()
        )
        question_rows = (
            (await connection.execute(sa.text(_EDIT_QUESTIONS), {"job_ids": job_ids}))
            .mappings()
            .all()
        )
        answer_rows = (
            (await connection.execute(sa.text(_EDIT_ANSWERS), {"ids": application_ids}))
            .mappings()
            .all()
        )
        resume_rows = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT id, label, drive_url, is_default FROM resumes "
                        "WHERE enrollment_id = :enrollment_id ORDER BY created_at, id"
                    ),
                    {"enrollment_id": enrollment_id},
                )
            )
            .mappings()
            .all()
        )
        # Override resolution goes through the ORM, so it needs a session bound
        # to the connection this screen already holds.
        async with AsyncSession(bind=connection) as session:
            windows = {
                cast(UUID, row["id"]): await _window(
                    session, row, enrollment_id=enrollment_id, now=now
                )
                for row in rows
            }

    questions: dict[UUID, list[dict[str, object]]] = {}
    indexed_questions: dict[UUID, dict[str, object]] = {}
    for question in question_rows:
        question_id = cast(UUID, question["id"])
        rendered = indexed_questions.get(question_id)
        if rendered is None:
            rendered = {
                "question_id": str(question_id),
                "text": str(question["text"]),
                "qtype": str(question["qtype"]),
                "required": bool(question["required"]),
                "ord": int(question["ord"]),
                "options": [],
            }
            indexed_questions[question_id] = rendered
            questions.setdefault(cast(UUID, question["job_id"]), []).append(rendered)
        if question["option_id"] is not None:
            cast(list[str], rendered["options"]).append(str(question["option_text"]))

    answers: dict[UUID, list[dict[str, object]]] = {}
    for answer in answer_rows:
        answers.setdefault(cast(UUID, answer["application_id"]), []).append(
            {
                "question_id": str(cast(UUID, answer["question_id"])),
                "value": answer["value"],
            }
        )

    events: dict[UUID, list[dict[str, object]]] = {}
    for event in timeline:
        events.setdefault(cast(UUID, event["application_id"]), []).append(
            {
                "event_type": str(event["event_type"]),
                "from_status": event["from_status"],
                "to_status": event["to_status"],
                "reason": event["reason"],
                "at": _iso(event["created_at"]),
            }
        )

    applications: list[dict[str, object]] = []
    for row in rows:
        can_edit, can_withdraw, reasons = windows[cast(UUID, row["id"])]
        applications.append(
            {
                "id": str(cast(UUID, row["id"])),
                "status": str(row["status"]),
                "applied_at": _iso(row["applied_at"]),
                "resume_url": str(row["resume_url"]),
                "answer_count": int(row["answer_count"]),
                "job": {
                    "id": str(cast(UUID, row["job_id"])),
                    "title": str(row["title"]),
                    "outcome": str(row["outcome"]),
                    "company": str(row["company_name"]),
                    "application_deadline": _iso(row["application_deadline"]),
                    "cancelled": row["cancelled_at"] is not None,
                },
                "cycle": {
                    "id": str(cast(UUID, row["cycle_id"])),
                    "name": str(row["cycle_name"]),
                    "kind": str(row["cycle_kind"]),
                    "archived": row["archived_at"] is not None,
                },
                # An open-cycle application holds no position, and a pipeline
                # one names the round it is sitting in rather than a number the
                # student would have to count out themselves (JOB-6, RND-1).
                "round": (
                    {
                        "name": str(row["round_name"]),
                        "ord": int(row["round_ord"]),
                        "of": int(row["round_count"]),
                    }
                    if row["current_round_id"] is not None
                    else None
                ),
                "can_edit": can_edit,
                "can_withdraw": can_withdraw,
                "edit_form": {
                    "questions": questions.get(cast(UUID, row["job_id"]), []),
                    "answers": answers.get(cast(UUID, row["id"]), []),
                },
                "window_reasons": reasons,
                "timeline": events.get(cast(UUID, row["id"]), []),
            }
        )

    live = sum(
        1 for row in rows if ApplicationStatus(row["status"]) is ApplicationStatus.IN_PROGRESS
    )
    return {
        # The enrollment the commands on this screen must name.  It comes from
        # the payload rather than from the /me bootstrap because a *different*
        # query being slow, stale or unmocked must not silently hide the
        # Withdraw button on an application the server would happily withdraw:
        # that is the same "the card offers what the command refuses" drift,
        # pointing the other way.
        "enrollment_id": str(enrollment_id),
        "resumes": [
            {
                "id": str(cast(UUID, resume["id"])),
                "label": str(resume["label"]),
                "drive_url": str(resume["drive_url"]),
                "is_default": bool(resume["is_default"]),
            }
            for resume in resume_rows
        ],
        "applications": applications,
        "counts": {"total": len(applications), "in_progress": live},
    }


_JOB_HEADER = """
    SELECT j.id, j.title, j.outcome, j.is_published, j.cancelled_at,
           j.application_deadline, c.id AS cycle_id, c.name AS cycle_name,
           c.kind AS cycle_kind, c.archived_at, co.id AS company_id,
           co.name AS company_name
    FROM jobs j
    JOIN companies co ON co.id = j.company_id
    JOIN cycles c ON c.id = j.cycle_id
    WHERE j.id = :job_id
"""


async def staff_job_board(engine: AsyncEngine, job_id: UUID) -> dict[str, object] | None:
    """The ATS board: every applicant, by the round they are sitting in (RND-1).

    Each row carries what the four bulk operations *would* do to it, computed
    by ``plan_row`` -- the same function the commands run.  That is what makes
    the board's buttons honest: a row the board offers Advance on is a row the
    command advances, and a row it does not is one the command would refuse
    (the design review section 4.22).
    """
    async with engine.connect() as connection:
        header = (
            (await connection.execute(sa.text(_JOB_HEADER), {"job_id": job_id}))
            .mappings()
            .one_or_none()
        )
        if header is None:
            return None
        applications, rounds = await board_rows(connection, job_id)
        reached_by_round = {
            job_round.id: tuple(
                BoardRow(
                    application_id=row.application_id,
                    enrollment_id=row.enrollment_id,
                    status=row.status,
                    current_round_id=row.current_round_id,
                    state_id=row.state_id,
                    result=row.result,
                    attendance=row.attendance,
                    venue_override=row.venue_override,
                    scheduled_at_override=row.scheduled_at_override,
                    notified_at=row.notified_at,
                    email=row.email,
                    roll_number=row.roll_number,
                    full_name=row.full_name,
                    round_ord=job_round.ord,
                    round_name=job_round.name,
                )
                for row in await round_state_rows(connection, job_id=job_id, round_id=job_round.id)
                if row.state_id is not None
            )
            for job_round in rounds
        }
        question_rows = (
            (
                await connection.execute(
                    sa.text(
                        "SELECT id, text FROM job_questions WHERE job_id = :job_id ORDER BY ord"
                    ),
                    {"job_id": job_id},
                )
            )
            .mappings()
            .all()
        )
        preset = await connection.scalar(
            sa.text("SELECT columns FROM export_presets WHERE job_id = :job_id"),
            {"job_id": job_id},
        )

    questions = tuple((cast(UUID, row["id"]), str(row["text"])) for row in question_rows)
    frozen = header["archived_at"] is not None or header["cancelled_at"] is not None
    columns: list[dict[str, object]] = []
    for job_round in rounds:
        members = list(reached_by_round[job_round.id])
        columns.append(
            {
                **_board_round(
                    job_round,
                    cycle_archived=header["archived_at"] is not None,
                    job_cancelled=header["cancelled_at"] is not None,
                ),
                "count": len(members),
                "rows": [
                    _board_entry(
                        row,
                        rounds,
                        frozen=frozen,
                        viewed_round=job_round,
                    )
                    for row in members
                ],
            }
        )

    # An application with no round position at all (JOB-6) is not finished with:
    # an open-cycle job carries no rounds, so *every* live applicant to one sits
    # here, waiting to be offered or eliminated.  Keeping them in the settled
    # bucket rendered them uncheckable and made the board offer a pipeline the
    # job does not have.
    unrouted = [
        row
        for row in applications
        if row.current_round_id is None and row.status is ApplicationStatus.IN_PROGRESS
    ]
    # Everyone the pipeline really has finished with: out, offered, or accepted.
    settled = [row for row in applications if row.status is not ApplicationStatus.IN_PROGRESS]
    return {
        "job": {
            "id": str(cast(UUID, header["id"])),
            "title": str(header["title"]),
            "company": str(header["company_name"]),
            "company_id": str(cast(UUID, header["company_id"])),
            "outcome": str(header["outcome"]),
            "is_published": bool(header["is_published"]),
            "cancelled": header["cancelled_at"] is not None,
            # A job with no rounds runs no pipeline (JOB-6).  The board reads
            # this to stop offering advance/waitlist/promote, which `plan_row`
            # can only ever refuse when nobody holds a round position.
            "has_rounds": len(rounds) > 0,
        },
        "cycle": {
            "id": str(cast(UUID, header["cycle_id"])),
            "name": str(header["cycle_name"]),
            "kind": str(header["cycle_kind"]),
            "archived": header["archived_at"] is not None,
        },
        "rounds": [
            _board_round(
                item,
                cycle_archived=header["archived_at"] is not None,
                job_cancelled=header["cancelled_at"] is not None,
            )
            for item in rounds
        ],
        "columns": columns,
        "unrouted": [_board_entry(row, rounds, frozen=frozen) for row in unrouted],
        "settled": [_board_entry(row, rounds, frozen=frozen) for row in settled],
        "export_columns": [
            {"key": item.key, "label": item.label, "family": item.family}
            for item in application_registry(questions)
        ],
        "export_preset": [str(item) for item in preset] if preset is not None else None,
        "counts": {
            "total": len(applications),
            "in_pipeline": sum(
                1
                for row in applications
                if row.current_round_id is not None and row.status is ApplicationStatus.IN_PROGRESS
            ),
            "unrouted": len(unrouted),
            "settled": len(settled),
        },
    }


def _board_round(
    job_round: JobRound, *, cycle_archived: bool, job_cancelled: bool
) -> dict[str, object]:
    blocked = round_finalization_blocker(
        job_round,
        cycle_archived=cycle_archived,
        job_cancelled=job_cancelled,
    )
    return {
        "id": str(job_round.id),
        "ord": job_round.ord,
        "name": job_round.name,
        "finalized_at": _iso(job_round.finalized_at),
        "finalized_by": (
            {
                "id": str(job_round.finalized_by),
                "name": job_round.finalized_by_name,
            }
            if job_round.finalized_by is not None
            else None
        ),
        "actions": {"finalize": _permission(blocked)},
    }


def _board_entry(
    row: BoardRow,
    rounds: tuple[JobRound, ...],
    *,
    frozen: bool,
    viewed_round: JobRound | None = None,
) -> dict[str, object]:
    """One applicant, with what each operation would do to them.

    ``frozen`` is the archived-or-cancelled case: ``check_scope`` refuses every
    cycle-scoped command on an archived cycle before the decider runs, so the
    board must not offer an action the server has already closed the door on.
    """
    is_current_round = (
        viewed_round is None or row.current_round_id == viewed_round.id
    ) and row.status is ApplicationStatus.IN_PROGRESS
    actions: dict[str, object] = {
        operation: _action(operation, row, rounds, frozen=frozen or not is_current_round)
        for operation in ("advance", "eliminate", "waitlist", "promote")
    }
    # The two round-scoped controls.  Both ask their own command's pure
    # decision, target-independent: "can this row be marked" and "can this row
    # be given a slot", which is exactly what the chip and the venue panel need
    # to know before anyone has chosen a value (the design review section 4.22).
    marking = plan_attendance(row, None, frozen=frozen or not is_current_round)
    slotting = slot_blocker(row, frozen=frozen or not is_current_round)
    actions["mark_attendance"] = _permission(marking if isinstance(marking, Reason) else None)
    actions["assign_venue"] = _permission(slotting)
    current = viewed_round or next(
        (item for item in rounds if item.id == row.current_round_id), None
    )
    return {
        "application_id": str(row.application_id),
        "enrollment_id": str(row.enrollment_id),
        "full_name": row.full_name,
        "roll_number": row.roll_number,
        "email": row.email,
        "status": row.status.value,
        "is_current_round": is_current_round,
        "round": (
            {
                "id": str(viewed_round.id if viewed_round is not None else row.current_round_id),
                "name": viewed_round.name if viewed_round is not None else row.round_name,
                "ord": viewed_round.ord if viewed_round is not None else row.round_ord,
            }
            if viewed_round is not None or row.current_round_id is not None
            else None
        ),
        "result": row.result.value if row.result is not None else None,
        "attendance": row.attendance.value if row.attendance is not None else None,
        # An override replaces the round's default rather than sitting beside
        # it, so the board states the slot this student actually has, and says
        # separately whether it is theirs alone (RND-1).
        "venue": row.venue_override or (current.venue if current is not None else None),
        "scheduled_at": _iso(
            row.scheduled_at_override or (current.scheduled_at if current is not None else None)
        ),
        "slot_is_override": (
            row.venue_override is not None or row.scheduled_at_override is not None
        ),
        "slot_notified_at": _iso(row.notified_at),
        "actions": actions,
    }


def _permission(reason: Reason | None) -> dict[str, object]:
    return {
        "allowed": reason is None,
        "reason": reason.code if reason is not None else None,
        "human": reason.human if reason is not None else None,
    }


def _action(
    operation: str, row: BoardRow, rounds: tuple[JobRound, ...], *, frozen: bool
) -> dict[str, object]:
    if frozen:
        return {"allowed": False, "reason": CYCLE_ARCHIVED, "to_status": None}
    planned = plan_row(cast(Operation, operation), row, rounds)
    if isinstance(planned, Reason):
        return {"allowed": False, "reason": planned.code, "to_status": None}
    return {
        "allowed": True,
        "reason": None,
        "to_status": planned.to_status.value,
        "to_round": planned.to_round.name if planned.to_round is not None else None,
    }
