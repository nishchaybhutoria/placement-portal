"""PRO-1/2: explicit, session-qualified study years; no inferred progression."""

import pytest
from pydantic import ValidationError

from app.domain.academics import (
    academic_session,
    academic_standing_reasons,
    academic_standing_status,
    session_label,
)
from app.modules.profiles.fields import FieldValueError, coerce_field
from app.modules.taxonomies.commands import SetSettingInput, SettingKey


@pytest.mark.parametrize("year", range(1, 9))
def test_PRO1_study_year_accepts_all_eight_years(year: int) -> None:
    assert coerce_field("study_year", year) == year
    assert coerce_field("study_year", str(year)) == year


@pytest.mark.parametrize("value", [0, 9, -1, 2027, True, False, 1.5, "first", "NaN", float("inf")])
def test_PRO1_study_year_rejects_invalid_values(value: object) -> None:
    with pytest.raises(FieldValueError):
        coerce_field("study_year", value)


@pytest.mark.parametrize("fields", [
    {"study_year": 3},
    {"study_year_session": 2026},
    {"study_year": 3, "study_year_session": None},
    {"study_year": None, "study_year_session": 2026},
])
def test_PRO2_requires_both_fields_even_when_other_half_was_previously_recorded(
    fields: dict[str, object],
) -> None:
    assert academic_standing_reasons(fields)


def test_PRO1_stale_browser_cannot_confirm_a_different_session() -> None:
    fields = {"study_year": 3, "study_year_session": 2025}
    assert academic_standing_reasons(fields, student=True, current_session=2026)
    assert academic_standing_reasons(fields, student=True, current_session=None)
    # An admin may honestly record a historical session; it must stay stale.
    assert not academic_standing_reasons(fields)
    assert academic_standing_status(fields, 2026)["status"] == "stale"
    assert fields["study_year"] == 3


def test_PRO1_clear_both_fields_or_edit_unrelated_fields_without_relabelling() -> None:
    assert not academic_standing_reasons({"study_year": None, "study_year_session": None})
    assert not academic_standing_reasons({"cpi": "8.0"}, student=True, current_session=2026)


@pytest.mark.parametrize("profile, session, expected", [
    ({}, None, "unconfigured"),
    ({}, 2026, "missing"),
    ({"study_year": 3, "study_year_session": 2025}, 2026, "stale"),
    ({"study_year": 3, "study_year_session": 2026}, 2026, "current"),
    ({"study_year": 8, "study_year_session": 2026}, 2026, "current"),
    ({"study_year": 9, "study_year_session": 2026}, 2026, "missing"),
    ({"study_year": True, "study_year_session": 2026}, 2026, "missing"),
    ({"study_year": 3, "study_year_session": None}, 2026, "missing"),
])
def test_PRO1_prompt_status_never_guesses_year(
    profile: dict[str, object], session: int | None, expected: str,
) -> None:
    status = academic_standing_status(profile, session)
    assert status["status"] == expected
    assert status["collection_only"] is True
    assert (status["min_year"], status["max_year"]) == (1, 8)


@pytest.mark.parametrize("value", [None, "2026", True, 1899, 2101, 2026.0])
def test_TAX_unconfigured_or_invalid_session_has_no_calendar_default(value: object) -> None:
    assert academic_session(value) is None


@pytest.mark.parametrize("value", ["2026", True, 1899, 2101, 2026.5])
def test_TAX_setting_accepts_only_valid_session_start_years(value: object) -> None:
    with pytest.raises(ValidationError):
        SetSettingInput(key=SettingKey.ACADEMIC_SESSION_START_YEAR, value=value)


def test_TAX_session_setting_can_be_paused_and_labels_roll_over() -> None:
    assert SetSettingInput(key=SettingKey.ACADEMIC_SESSION_START_YEAR, value=None).value is None
    assert academic_session(2026) == 2026
    assert session_label(2026) == "2026–27"
    assert session_label(2099) == "2099–00"
