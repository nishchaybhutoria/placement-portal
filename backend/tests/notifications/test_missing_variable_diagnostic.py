"""The warning for a blank template variable has to say which variable.

``render_text`` is fail-open by design: a missing value renders blank and warns
rather than stalling the outbox. That is only a safe trade while the warning is
readable. In the mock run it was not -- 116 of them fired, and ``JsonFormatter``
dropped the ``variable`` and ``part`` extras, so every one read "Notification
template variable is missing" without naming anything. Ninety-four envelopes
went out addressed to nobody underneath a diagnostic that was working.
"""

from __future__ import annotations

import json
import logging

import pytest

from app.modules.notifications.render import render_text
from app.observability import JsonFormatter


def test_NTF_a_blank_variable_warning_names_the_variable_and_the_part(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.modules.notifications.render"):
        rendered = render_text(
            "Dear {student},", {}, event_key="membership_pending", part="body"
        )

    assert rendered.missing == ("student",)
    record = next(
        item for item in caplog.records if "variable is missing" in item.getMessage()
    )
    payload = json.loads(JsonFormatter().format(record))

    assert payload["variable"] == "student"
    assert payload["part"] == "body"
    assert payload["event_key"] == "membership_pending"


def test_NTF_the_diagnostic_still_carries_no_notification_content() -> None:
    """Naming the variable is not naming its value (OBSERVABILITY section 4)."""
    record = logging.LogRecord("test", logging.WARNING, __file__, 1, "blank", (), None)
    record.variable = "student"
    record.part = "body"
    record.recipient = "student@example.edu"
    record.body = "Dear Rhea,"

    payload = json.loads(JsonFormatter().format(record))

    assert payload["variable"] == "student"
    assert "recipient" not in payload
    assert "body" not in payload
