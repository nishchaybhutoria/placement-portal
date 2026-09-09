"""Typed validation of an application's answers (Behavior APP-1, APP-3).

Pure: the form schema comes from the job's questions, the values come from the
student, and this module says which values are acceptable.  ``apply`` and
``edit_application`` both replace the answer set wholesale, so both validate
through here and neither can be lenient where the other is strict.

Every failure names the question it belongs to in its ``path``
(``answers.<question_id>``), because a form with fifteen questions and one
reason that says "invalid answer" is unactionable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

from app.core.errors import (
    ANSWER_INVALID,
    ANSWER_REQUIRED,
    UNKNOWN_QUESTION,
)
from app.core.plan import Reason
from app.domain.shared import QuestionType
from app.modules.profiles.fields import EMAIL_PATTERN

# PRO-3's Drive-link check is the shape rule for URL-typed answers too, but only
# for the resume; a URL *answer* is any https link -- a student asked for their
# GitHub must not be told it has to live on Google Drive.
_URL_PREFIX = "https://"


@dataclass(frozen=True, slots=True)
class QuestionSpec:
    """One question as the form presents it."""

    id: UUID
    text: str
    qtype: QuestionType
    required: bool
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidatedAnswers:
    values: dict[UUID, object]
    failures: tuple[Reason, ...]


def _path(question_id: UUID) -> str:
    return f"answers.{question_id}"


def _invalid(question: QuestionSpec, human: str) -> Reason:
    return Reason(code=ANSWER_INVALID, human=human, path=_path(question.id))


def _validate_one(question: QuestionSpec, value: object) -> tuple[object | None, Reason | None]:
    """Return the value to store, or the reason it cannot be stored."""
    match question.qtype:
        case QuestionType.TEXT | QuestionType.LONGTEXT:
            if not isinstance(value, str):
                return None, _invalid(question, "Answer with text.")
            return value.strip(), None
        case QuestionType.SINGLE:
            if not isinstance(value, str) or value not in question.options:
                return None, _invalid(question, "Choose one of the listed options.")
            return value, None
        case QuestionType.MULTI:
            if not isinstance(value, list) or any(
                not isinstance(item, str) or item not in question.options for item in value
            ):
                return None, _invalid(question, "Choose from the listed options.")
            if len(set(value)) != len(value):
                return None, _invalid(question, "Choose each option at most once.")
            return list(value), None
        case QuestionType.BOOLEAN:
            if not isinstance(value, bool):
                return None, _invalid(question, "Answer yes or no.")
            return value, None
        case QuestionType.NUMBER:
            if isinstance(value, bool) or not isinstance(value, (int, float, str)):
                return None, _invalid(question, "Answer with a number.")
            try:
                number = Decimal(str(value))
            except InvalidOperation:
                return None, _invalid(question, "Answer with a number.")
            # Stored as a string so the JSONB value survives a round trip at
            # full precision; a float would quietly re-round it.
            return str(number), None
        case QuestionType.DATE:
            if not isinstance(value, str):
                return None, _invalid(question, "Answer with a date (YYYY-MM-DD).")
            try:
                parsed = date.fromisoformat(value)
            except ValueError:
                return None, _invalid(question, "Answer with a date (YYYY-MM-DD).")
            return parsed.isoformat(), None
        case QuestionType.EMAIL:
            if not isinstance(value, str) or not EMAIL_PATTERN.match(value.strip()):
                return None, _invalid(question, "Answer with an email address.")
            return value.strip(), None
        case QuestionType.URL:
            if not isinstance(value, str) or not value.strip().startswith(_URL_PREFIX):
                return None, _invalid(question, "Answer with an https link.")
            return value.strip(), None


def _is_blank(value: object) -> bool:
    """What counts as "not answered" -- false and zero do not."""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


def validate_answers(
    questions: tuple[QuestionSpec, ...], submitted: dict[UUID, object]
) -> ValidatedAnswers:
    """Validate a wholesale answer set against the job's form (APP-1).

    Unknown question ids are rejected rather than dropped: a stale form posting
    answers to questions the coordinator has since removed means the student is
    looking at a form that no longer exists, and silently discarding half their
    submission would be worse than telling them.
    """
    known = {question.id: question for question in questions}
    failures: list[Reason] = []
    values: dict[UUID, object] = {}

    for question_id in submitted:
        if question_id not in known:
            failures.append(
                Reason(
                    code=UNKNOWN_QUESTION,
                    human="This form has changed; reload it and answer again.",
                    path=_path(question_id),
                )
            )

    for question in questions:
        value = submitted.get(question.id)
        if _is_blank(value):
            if question.required:
                failures.append(
                    Reason(
                        code=ANSWER_REQUIRED,
                        human=f"{question.text} is required.",
                        path=_path(question.id),
                    )
                )
            continue
        stored, failure = _validate_one(question, value)
        if failure is not None:
            failures.append(failure)
        else:
            values[question.id] = stored

    return ValidatedAnswers(values=values, failures=tuple(failures))
