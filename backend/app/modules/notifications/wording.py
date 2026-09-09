"""How a value is written to the person who receives it.

Pure, and called from inside ``decide``: a notification context travels to the
worker as JSON on a queued job, and ``render_text`` substitutes names without
formatting anything, so whatever an emitter puts in the context is literally
what the student reads. Two consequences the mock D.33 review found the hard
way -- a raw ``datetime`` reached a student as ``2027-07-01T04:00:00+00:00``,
and a raw enum reached one as ``accepted_another_offer``.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.modules.applications.slots import IST

#: Every student-facing instant is rendered in IST with the zone named, in the
#: product's own date format (``frontend/src/lib/date.ts``). the design review 4.5
#: fixes IST as the interpretation of an uploaded venue sheet; an email that
#: read the same 09:30 slot back as 04:00 was five and a half hours early, and
#: finalization turns a missed round into a strike.
TIME_FORMAT = "%d %b %Y, %H:%M IST"

#: A schedule that does not exist yet, rather than a blank promise.
UNSCHEDULED = "to be announced"
#: An offer with no acceptance deadline configured, rather than a blank line a
#: student cannot tell from "expires tomorrow".
NO_DEADLINE = "no fixed deadline"
#: A round-shaped field on something that did not come from a round.
NOT_APPLICABLE = "not applicable"

# Mirrors frontend/src/lib/text.ts, so an email and the screen behind it say
# the same word for the same enum.
_ACRONYMS = {
    "cpi": "CPI",
    "csv": "CSV",
    "ctc": "CTC",
    "id": "ID",
    "inr": "INR",
    "lpa": "LPA",
    "nirf": "NIRF",
    "ppo": "PPO",
    "rti": "RTI",
    "url": "URL",
    "xlsx": "XLSX",
}

#: Why an application was withdrawn without the student doing anything. These
#: are clauses rather than labels because the template reads "Reason: {trigger}"
#: and "accepted another offer" is the sentence, not the token.
WITHDRAWAL_TRIGGERS = {
    "accepted_another_offer": "you accepted another offer",
    "membership_exit": "your membership in the cycle ended",
    "archival": "the cycle was closed",
}

#: What became of an offer whose response deadline passed (``offer_expiry_t``).
EXPIRY_OUTCOMES = {
    "auto_decline": "declined automatically",
    "auto_accept": "accepted automatically",
}


def format_time(value: datetime | None, *, absent: str = UNSCHEDULED) -> str:
    """Render an instant as the student's own wall clock."""
    if value is None:
        return absent
    moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return moment.astimezone(IST).strftime(TIME_FORMAT)


def format_deadline(value: datetime | None) -> str:
    """A deadline that was never set says so; a blank line cannot be read."""
    return format_time(value, absent=NO_DEADLINE)


def or_absent(value: str | None, absent: str = UNSCHEDULED) -> str:
    """Text that may not exist yet, named rather than left blank."""
    return value if value else absent


def humanise(value: str) -> str:
    """Turn a wire-format enum into copy: ``off_campus`` -> ``Off campus``."""
    words = value.split("_")
    rendered: list[str] = []
    for index, word in enumerate(words):
        acronym = _ACRONYMS.get(word.lower())
        if acronym is not None:
            rendered.append(acronym)
        elif index == 0:
            rendered.append(word[:1].upper() + word[1:])
        else:
            rendered.append(word.lower())
    return " ".join(rendered)


def withdrawal_trigger(value: str) -> str:
    """The clause naming why an application was withdrawn automatically."""
    return WITHDRAWAL_TRIGGERS.get(value, humanise(value).lower())


def expiry_outcome(value: str) -> str:
    """What the portal did with an offer nobody answered."""
    return EXPIRY_OUTCOMES.get(value, humanise(value).lower())


def schedule_note(is_update: bool) -> str:
    """Whether a published schedule replaces one already sent.

    The template used to print ``Updated schedule: {is_update}``, which reached
    fifteen students as ``Updated schedule: False`` -- a Python literal telling
    a reader that something is not an update.
    """
    if is_update:
        return "This replaces the schedule sent to you earlier."
    return "This is the first schedule published for this round."
