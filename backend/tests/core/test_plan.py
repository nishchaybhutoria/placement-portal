"""M2 contracts for the LLD section 5 plan types."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from app.core.plan import Deferred, Plan, Reason, Rejection, StateOp


def test_plan_values_are_immutable_command_decisions() -> None:
    operation = StateOp(op="insert", model="audit_log", values={"action": "ping"})
    deferred = Deferred(
        task="deliver_notification",
        args={"event_key": "ping"},
        schedule_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    plan = Plan(
        state_ops=[operation],
        events=[],
        deferred=[deferred],
        audit=None,
        summary={"accepted": True},
    )

    assert plan.state_ops == [operation]
    assert plan.deferred[0].schedule_at == datetime(2030, 1, 1, tzinfo=UTC)
    with pytest.raises(FrozenInstanceError):
        operation.model = "users"  # type: ignore[misc]


def test_rejection_keeps_structured_reason_path() -> None:
    rejection = Rejection(
        reasons=[Reason(code="profile_incomplete", human="Program is required", path="program")]
    )

    assert rejection.reasons[0].path == "program"
