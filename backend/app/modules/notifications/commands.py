"""Notification templates, delivery logging, and dead-letter commands (NTF)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import INVALID_REQUEST
from app.core.plan import ActorContext, Deferred, Plan, Reason, Rejection, ScopeIds, StateOp
from app.core.registry import Registry
from app.domain.shared import NotificationStatus
from app.modules.notifications.catalog import EVENT_KEY_SET
from app.modules.notifications.queries import ResolvedTemplate, resolve_template
from app.modules.notifications.render import named_variables, render_text

LOGGER = logging.getLogger(__name__)
MAX_DELIVERY_ATTEMPTS = 5

TEMPLATE_NOT_FOUND = "template_not_found"
NOTIFICATION_NOT_FOUND = "notification_not_found"
NOTIFICATION_NOT_DEAD = "notification_not_dead"


class UpdateTemplateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_key: str
    cycle_id: UUID | None = None
    subject: str = Field(min_length=1)
    body: str = Field(min_length=1)
    enabled: bool

    @field_validator("event_key")
    @classmethod
    def known_event_key(cls, value: str) -> str:
        if value not in EVENT_KEY_SET:
            raise ValueError("event_key must be in the effective notification catalog")
        return value

    @field_validator("subject", "body")
    @classmethod
    def named_template(cls, value: str) -> str:
        named_variables(value)
        return value


class UpdateTemplateSummary(BaseModel):
    template_id: UUID
    event_key: str
    cycle_id: UUID | None
    created: bool
    enabled: bool


@dataclass(frozen=True, slots=True)
class TemplateState:
    scope_ids: ScopeIds
    cycle_exists: bool
    existing_id: UUID | None


async def _load_template(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> TemplateState:
    if not isinstance(input_value, UpdateTemplateInput):
        raise TypeError("update_template requires UpdateTemplateInput")
    cycle_exists = input_value.cycle_id is None or bool(
        await tx.scalar(
            sa.text("SELECT EXISTS (SELECT 1 FROM cycles WHERE id = :id)"),
            {"id": input_value.cycle_id},
        )
    )
    statement = (
        "SELECT id FROM notification_templates "
        "WHERE event_key = :event_key AND cycle_id IS NOT DISTINCT FROM :cycle_id"
    )
    if lock:
        statement += " FOR UPDATE"
    existing_id = cast(
        "UUID | None",
        await tx.scalar(
            sa.text(statement),
            {"event_key": input_value.event_key, "cycle_id": input_value.cycle_id},
        ),
    )
    return TemplateState(
        scope_ids=ScopeIds(cycle_id=input_value.cycle_id),
        cycle_exists=cycle_exists,
        existing_id=existing_id,
    )


def _decide_update_template(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """NTF: edit a global template or create/update a per-cycle override."""
    if not isinstance(input_value, UpdateTemplateInput) or not isinstance(state, TemplateState):
        raise TypeError("Invalid update_template decision input")
    if not state.cycle_exists:
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_REQUEST,
                    human="The cycle does not exist",
                    path="cycle_id",
                )
            ]
        )
    template_id = state.existing_id or uuid5(
        NAMESPACE_URL,
        f"cds:notification-template:{input_value.event_key}:{input_value.cycle_id or 'global'}",
    )
    values: dict[str, object] = {
        "event_key": input_value.event_key,
        "cycle_id": input_value.cycle_id,
        "subject": input_value.subject,
        "body": input_value.body,
        "enabled": input_value.enabled,
    }
    operation = (
        StateOp(
            op="update",
            model="notification_templates",
            values=values,
            where={"id": template_id},
        )
        if state.existing_id is not None
        else StateOp(
            op="insert",
            model="notification_templates",
            values={"id": template_id, **values},
        )
    )
    return Plan(
        state_ops=[operation],
        events=[],
        deferred=[],
        audit={
            "subject_type": "notification_template",
            "subject_id": template_id,
            "details": {
                "event_key": input_value.event_key,
                "cycle_id": str(input_value.cycle_id) if input_value.cycle_id else None,
                "enabled": input_value.enabled,
                "created": state.existing_id is None,
            },
        },
        summary={
            "template_id": str(template_id),
            "event_key": input_value.event_key,
            "cycle_id": str(input_value.cycle_id) if input_value.cycle_id else None,
            "created": state.existing_id is None,
            "enabled": input_value.enabled,
        },
    )


class DeliverNotificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: UUID
    event_key: str
    recipient: str = Field(min_length=3)
    context: dict[str, object]

    @field_validator("event_key")
    @classmethod
    def known_event_key(cls, value: str) -> str:
        if value not in EVENT_KEY_SET:
            raise ValueError("event_key must be in the effective notification catalog")
        return value


class DeliverNotificationSummary(BaseModel):
    notification_id: UUID
    should_send: bool
    subject: str
    body: str
    sender: str
    attempts: int


@dataclass(frozen=True, slots=True)
class DeliveryState:
    scope_ids: ScopeIds
    now: datetime
    template: ResolvedTemplate | None
    subject: str
    body: str
    sender: str
    existing_event_key: str | None
    existing_recipient: str | None
    status: NotificationStatus | None
    attempts: int


def _context_cycle_id(context: dict[str, object]) -> UUID | None:
    raw = context.get("cycle_id")
    if isinstance(raw, UUID):
        return raw
    if isinstance(raw, str):
        try:
            return UUID(raw)
        except ValueError:
            LOGGER.warning(
                "Notification context has an invalid cycle_id; using the global template",
                extra={"cycle_id": raw},
            )
    return None


async def _load_delivery(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> DeliveryState:
    if not isinstance(input_value, DeliverNotificationInput):
        raise TypeError("deliver_notification requires DeliverNotificationInput")
    statement = "SELECT event_key, recipient, status, attempts FROM notification_log WHERE id = :id"
    if lock:
        statement += " FOR UPDATE"
    existing = (
        (await tx.execute(sa.text(statement), {"id": input_value.notification_id}))
        .mappings()
        .one_or_none()
    )
    cycle_id = _context_cycle_id(input_value.context)
    template = await resolve_template(tx, input_value.event_key, cycle_id)
    if template is None:
        # The build gate proves every production emitter has a global seed.  A
        # missing row at runtime is therefore data corruption, not a reason to
        # silently discard a mandated notification.
        raise RuntimeError(
            f"Notification template {input_value.event_key!r} is missing from the database"
        )
    subject = render_text(
        template.subject,
        input_value.context,
        event_key=input_value.event_key,
        part="subject",
    ).text
    body = render_text(
        template.body,
        input_value.context,
        event_key=input_value.event_key,
        part="body",
    ).text
    sender_value = await tx.scalar(
        sa.text("SELECT value #>> '{}' FROM settings WHERE key = 'ses_sender'")
    )
    now = cast(datetime, await tx.scalar(sa.select(sa.func.now())))
    return DeliveryState(
        scope_ids=ScopeIds(cycle_id=cycle_id),
        now=now,
        template=template,
        subject=subject,
        body=body,
        sender=str(sender_value) if sender_value is not None else "",
        existing_event_key=str(existing["event_key"]) if existing is not None else None,
        existing_recipient=str(existing["recipient"]) if existing is not None else None,
        status=NotificationStatus(existing["status"]) if existing is not None else None,
        attempts=int(existing["attempts"]) if existing is not None else 0,
    )


def _decide_delivery(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """NTF: resolve/render and create one idempotent delivery log row."""
    if not isinstance(input_value, DeliverNotificationInput) or not isinstance(
        state, DeliveryState
    ):
        raise TypeError("Invalid deliver_notification decision input")
    if state.existing_event_key is not None and (
        state.existing_event_key != input_value.event_key
        or state.existing_recipient is None
        or state.existing_recipient.casefold() != input_value.recipient.casefold()
    ):
        return Rejection(
            reasons=[
                Reason(
                    code=INVALID_REQUEST,
                    human="The notification id belongs to a different delivery intent",
                    path="notification_id",
                )
            ]
        )
    should_send = (
        state.template is not None
        and state.template.enabled
        and state.status not in {NotificationStatus.SENT, NotificationStatus.DEAD}
        and state.attempts < MAX_DELIVERY_ATTEMPTS
    )
    operations: list[StateOp] = []
    if should_send:
        if state.status is None:
            operations.append(
                StateOp(
                    op="insert",
                    model="notification_log",
                    values={
                        "id": input_value.notification_id,
                        "recipient": input_value.recipient,
                        "event_key": input_value.event_key,
                        "subject": state.subject,
                        "status": NotificationStatus.QUEUED.value,
                        "attempts": 0,
                        "context": input_value.context,
                    },
                )
            )
        else:
            # A retry or staff resend resolves the template again.  Keep the
            # log's subject/context aligned with what this attempt will send.
            operations.append(
                StateOp(
                    op="update",
                    model="notification_log",
                    values={"subject": state.subject, "context": input_value.context},
                    where={"id": input_value.notification_id},
                )
            )
    return Plan(
        state_ops=operations,
        events=[],
        deferred=[],
        audit=None,
        summary={
            "notification_id": str(input_value.notification_id),
            "should_send": should_send,
            "subject": state.subject,
            "body": state.body,
            "sender": state.sender,
            "attempts": state.attempts,
        },
    )


class RecordNotificationAttemptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: UUID
    delivered: bool
    error: str | None = None


class RecordNotificationAttemptSummary(BaseModel):
    notification_id: UUID
    status: NotificationStatus
    attempts: int


@dataclass(frozen=True, slots=True)
class AttemptState:
    scope_ids: ScopeIds
    exists: bool
    status: NotificationStatus
    attempts: int
    now: datetime


async def _load_attempt(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> AttemptState:
    if not isinstance(input_value, RecordNotificationAttemptInput):
        raise TypeError("record_notification_attempt requires RecordNotificationAttemptInput")
    statement = "SELECT status, attempts FROM notification_log WHERE id = :id"
    if lock:
        statement += " FOR UPDATE"
    row = (
        (await tx.execute(sa.text(statement), {"id": input_value.notification_id}))
        .mappings()
        .one_or_none()
    )
    return AttemptState(
        scope_ids=ScopeIds(),
        exists=row is not None,
        status=(NotificationStatus(row["status"]) if row is not None else NotificationStatus.DEAD),
        attempts=int(row["attempts"]) if row is not None else 0,
        now=cast(datetime, await tx.scalar(sa.select(sa.func.now()))),
    )


def _decide_attempt(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """NTF: record exactly one external send attempt through the executor."""
    if not isinstance(input_value, RecordNotificationAttemptInput) or not isinstance(
        state, AttemptState
    ):
        raise TypeError("Invalid record_notification_attempt decision input")
    if not state.exists:
        return Rejection(
            reasons=[Reason(code=NOTIFICATION_NOT_FOUND, human="Notification not found")]
        )
    if state.status in {NotificationStatus.SENT, NotificationStatus.DEAD}:
        return Plan(
            state_ops=[],
            events=[],
            deferred=[],
            audit=None,
            summary={
                "notification_id": str(input_value.notification_id),
                "status": state.status.value,
                "attempts": state.attempts,
            },
        )
    attempts = state.attempts + 1
    status = (
        NotificationStatus.SENT
        if input_value.delivered
        else (
            NotificationStatus.DEAD
            if attempts >= MAX_DELIVERY_ATTEMPTS
            else NotificationStatus.FAILED
        )
    )
    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="notification_log",
                values={
                    "status": status.value,
                    "attempts": attempts,
                    "last_error": None if input_value.delivered else input_value.error,
                    "sent_at": state.now if input_value.delivered else None,
                },
                where={"id": input_value.notification_id},
            )
        ],
        events=[],
        deferred=[],
        audit=None,
        summary={
            "notification_id": str(input_value.notification_id),
            "status": status.value,
            "attempts": attempts,
        },
    )


class ResendNotificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notification_id: UUID


class ResendNotificationSummary(BaseModel):
    notification_id: UUID
    queued: bool


@dataclass(frozen=True, slots=True)
class ResendState:
    scope_ids: ScopeIds
    exists: bool
    status: NotificationStatus | None
    event_key: str | None
    recipient: str | None
    context: dict[str, object]
    template_enabled: bool


async def _load_resend(tx: AsyncSession, input_value: BaseModel, *, lock: bool) -> ResendState:
    if not isinstance(input_value, ResendNotificationInput):
        raise TypeError("resend_notification requires ResendNotificationInput")
    statement = "SELECT event_key, recipient, status, context FROM notification_log WHERE id = :id"
    if lock:
        statement += " FOR UPDATE"
    row = (
        (await tx.execute(sa.text(statement), {"id": input_value.notification_id}))
        .mappings()
        .one_or_none()
    )
    if row is None:
        return ResendState(ScopeIds(), False, None, None, None, {}, False)
    context = dict(row["context"] or {})
    template = await resolve_template(tx, str(row["event_key"]), _context_cycle_id(context))
    return ResendState(
        scope_ids=ScopeIds(cycle_id=_context_cycle_id(context)),
        exists=True,
        status=NotificationStatus(row["status"]),
        event_key=str(row["event_key"]),
        recipient=str(row["recipient"]),
        context=context,
        template_enabled=template is not None and template.enabled,
    )


def _decide_resend(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """NTF: requeue one dead letter; repeated execution changes no state twice."""
    if not isinstance(input_value, ResendNotificationInput) or not isinstance(state, ResendState):
        raise TypeError("Invalid resend_notification decision input")
    if not state.exists:
        return Rejection(
            reasons=[Reason(code=NOTIFICATION_NOT_FOUND, human="Notification not found")]
        )
    if state.status is not NotificationStatus.DEAD:
        return Rejection(
            reasons=[
                Reason(
                    code=NOTIFICATION_NOT_DEAD,
                    human="Only a dead notification can be resent",
                )
            ]
        )
    if not state.template_enabled:
        return Rejection(
            reasons=[
                Reason(
                    code=TEMPLATE_NOT_FOUND,
                    human="The resolved template is missing or disabled",
                )
            ]
        )
    assert state.event_key is not None and state.recipient is not None
    return Plan(
        state_ops=[
            StateOp(
                op="update",
                model="notification_log",
                values={
                    "status": NotificationStatus.QUEUED.value,
                    "attempts": 0,
                    "last_error": None,
                    "sent_at": None,
                },
                where={"id": input_value.notification_id},
            )
        ],
        events=[],
        deferred=[
            Deferred(
                task="deliver_notification",
                args={
                    "notification_id": str(input_value.notification_id),
                    "event_key": state.event_key,
                    "recipient": state.recipient,
                    "context": state.context,
                },
            )
        ],
        audit={
            "subject_type": "notification_log",
            "subject_id": input_value.notification_id,
            "details": {"operation": "resend_notification"},
        },
        summary={"notification_id": str(input_value.notification_id), "queued": True},
    )


def register_notification_commands(registry: Registry) -> None:
    registry.command(
        name="update_template",
        input_model=UpdateTemplateInput,
        output_model=UpdateTemplateSummary,
        actor="admin",
        scope="none",
        loader=_load_template,
        rule_domains=(),
        spec_ids=("NTF",),
    )(_decide_update_template)
    registry.command(
        name="resend_notification",
        input_model=ResendNotificationInput,
        output_model=ResendNotificationSummary,
        actor="staff",
        scope="none",
        loader=_load_resend,
        rule_domains=(),
        spec_ids=("NTF",),
    )(_decide_resend)
    registry.command(
        name="deliver_notification",
        input_model=DeliverNotificationInput,
        output_model=DeliverNotificationSummary,
        actor="system",
        scope="none",
        loader=_load_delivery,
        rule_domains=(),
        spec_ids=("NTF", "§16"),
        expose_http=False,
    )(_decide_delivery)
    registry.command(
        name="record_notification_attempt",
        input_model=RecordNotificationAttemptInput,
        output_model=RecordNotificationAttemptSummary,
        actor="system",
        scope="none",
        loader=_load_attempt,
        rule_domains=(),
        spec_ids=("NTF", "§16"),
        expose_http=False,
    )(_decide_attempt)
