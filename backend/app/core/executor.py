"""The sole transaction boundary for all CDS Portal commands (LLD section 5)."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Protocol, cast

import sqlalchemy as sa
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core import idempotency
from app.core.db import Base
from app.core.errors import (
    SESSION_EFFECT_IDEMPOTENCY,
    AuthorizationDenied,
    BulkInterrupted,
    DomainRejection,
    RateLimitExceeded,
)
from app.core.plan import (
    ActorContext,
    Deferred,
    Event,
    LoadedState,
    Preview,
    Reason,
    Rejection,
    Result,
    ScopeIds,
    StateOp,
)
from app.core.registry import CommandSpec, Registry
from app.domain.shared import RuleDomain
from app.models import MODEL_MODULES
from app.observability import command_finished, command_log_context, command_started

LOGGER = logging.getLogger(__name__)

AfterStateOp = Callable[[int], Awaitable[None]]
BeforeCommit = Callable[[], Awaitable[None]]
PolicyResolver = Callable[[object], object]
OverrideResolver = Callable[
    [AsyncSession, tuple[RuleDomain, ...], ScopeIds], Awaitable[object]
]


class Authorizer(Protocol):
    def check(self, spec: CommandSpec, actor: ActorContext, input_value: BaseModel) -> None: ...

    def check_scope(
        self, spec: CommandSpec, actor: ActorContext, state: LoadedState
    ) -> None: ...

    def check_replayed_scope(
        self, spec: CommandSpec, actor: ActorContext, scope_ids: ScopeIds
    ) -> None: ...


def _add_scope_log_context(
    context: dict[str, object], scope_ids: ScopeIds
) -> None:
    for field in ("cycle_id", "job_id", "enrollment_id", "application_id"):
        value = getattr(scope_ids, field)
        if value is not None:
            context[field] = str(value)


class AllowAllAuthorizer:
    def check(self, spec: CommandSpec, actor: ActorContext, input_value: BaseModel) -> None:
        del spec, actor, input_value

    def check_scope(
        self, spec: CommandSpec, actor: ActorContext, state: LoadedState
    ) -> None:
        del spec, actor, state

    def check_replayed_scope(
        self, spec: CommandSpec, actor: ActorContext, scope_ids: ScopeIds
    ) -> None:
        del spec, actor, scope_ids


async def _no_overrides(
    _tx: AsyncSession, _domains: tuple[RuleDomain, ...], _scope_ids: ScopeIds
) -> tuple[()]:
    return ()


def _no_policy(_state: object) -> None:
    return None


@dataclass(frozen=True, slots=True)
class ExecutorHooks:
    after_state_op: AfterStateOp | None = None
    before_commit: BeforeCommit | None = None


class Executor:
    def __init__(
        self,
        *,
        registry: Registry,
        session_factory: async_sessionmaker[AsyncSession],
        authorizer: Authorizer | None = None,
        policy_resolver: PolicyResolver = _no_policy,
        override_resolver: OverrideResolver = _no_overrides,
        hooks: ExecutorHooks | None = None,
    ) -> None:
        if not MODEL_MODULES:
            raise RuntimeError("Domain model registry is empty")
        self.registry = registry
        self.session_factory = session_factory
        self.authorizer = authorizer or AllowAllAuthorizer()
        self.policy_resolver = policy_resolver
        self.override_resolver = override_resolver
        self.hooks = hooks or ExecutorHooks()

    async def run(
        self,
        name: str,
        input_value: BaseModel,
        actor: ActorContext,
        *,
        dry_run: bool = False,
        idempotency_key: str | None = None,
        _batch_audit: dict[str, object] | None = None,
        _idempotency_fingerprint: str | None = None,
    ) -> Preview | Result:
        execution_id, token, started = command_started()
        log_context = command_log_context(input_value, actor)
        outcome = "error"
        try:
            result = await self._run_impl(
                name,
                input_value,
                actor,
                dry_run=dry_run,
                idempotency_key=idempotency_key,
                _batch_audit=_batch_audit,
                _idempotency_fingerprint=_idempotency_fingerprint,
                _log_context=log_context,
            )
            outcome = "success"
            return result
        except DomainRejection:
            outcome = "rejected"
            raise
        except AuthorizationDenied:
            outcome = "denied"
            raise
        finally:
            elapsed = command_finished(
                command=name,
                dry_run=dry_run,
                outcome=outcome,
                started=started,
                token=token,
            )
            LOGGER.info(
                "Command execution completed",
                extra={
                    **log_context,
                    "command": name,
                    "command_execution_id": execution_id,
                    "dry_run": dry_run,
                    "duration_ms": round(elapsed * 1000, 3),
                    "outcome": outcome,
                },
            )

    async def _run_impl(
        self,
        name: str,
        input_value: BaseModel,
        actor: ActorContext,
        *,
        dry_run: bool = False,
        idempotency_key: str | None = None,
        _batch_audit: dict[str, object] | None = None,
        _idempotency_fingerprint: str | None = None,
        _log_context: dict[str, object],
    ) -> Preview | Result:
        spec = self.registry.commands[name]
        self.authorizer.check(spec, actor, input_value)
        if spec.session_effect is not None and idempotency_key is not None:
            raise DomainRejection(
                Rejection(
                    reasons=[
                        Reason(
                            code=SESSION_EFFECT_IDEMPOTENCY,
                            human="Session-effect commands do not accept idempotency keys",
                        )
                    ]
                )
            )
        fingerprint = (
            _idempotency_fingerprint or idempotency.request_fingerprint(input_value)
            if idempotency_key is not None and not dry_run
            else None
        )

        async with self.session_factory() as tx:
            transaction = await tx.begin()
            try:
                owns_reservation = False
                if idempotency_key is not None and not dry_run:
                    assert fingerprint is not None
                    reservation = await idempotency.reserve(
                        tx,
                        idempotency_key,
                        name,
                        principal_id=actor.principal_id,
                        fingerprint=fingerprint,
                    )
                    if reservation.cached is not None:
                        if reservation.scope_ids is None:
                            raise RuntimeError("Cached result has no scope snapshot")
                        self.authorizer.check_replayed_scope(
                            spec, actor, reservation.scope_ids
                        )
                        _add_scope_log_context(_log_context, reservation.scope_ids)
                        await transaction.rollback()
                        return reservation.cached
                    owns_reservation = reservation.owned

                state_value = await spec.loader(tx, input_value, lock=not dry_run)
                state = cast(LoadedState, state_value)
                _add_scope_log_context(_log_context, state.scope_ids)
                self.authorizer.check_scope(spec, actor, state)
                overrides = await self.override_resolver(
                    tx, spec.rule_domains, state.scope_ids
                )
                policy = self.policy_resolver(state)
                decision = spec.decide(input_value, state, policy, overrides, actor)
                if isinstance(decision, Rejection):
                    raise DomainRejection(decision)
                spec.output_model.model_validate(decision.summary)
                if spec.execution_mode == "bulk" and not isinstance(
                    decision.summary.get("rows"), list
                ):
                    raise ValueError("Bulk command summary must contain a rows list")

                if dry_run:
                    await transaction.rollback()
                    return Preview(summary=decision.summary, events=decision.events)

                await self._apply_state_ops(tx, decision.state_ops)
                await self._append_events(tx, decision.events, actor)
                audit = decision.audit if spec.execution_mode == "single" else _batch_audit
                await self._write_audit(tx, actor, name, audit)
                for deferred in decision.deferred:
                    await self._defer(tx, deferred)

                result = Result(summary=decision.summary, events=decision.events)
                if idempotency_key is not None and owns_reservation:
                    assert fingerprint is not None
                    await idempotency.complete(
                        tx,
                        idempotency_key,
                        result,
                        principal_id=actor.principal_id,
                        fingerprint=fingerprint,
                        scope_ids=state.scope_ids,
                    )
                if self.hooks.before_commit is not None:
                    await self.hooks.before_commit()
                await transaction.commit()
                return result
            except BaseException:
                if transaction.is_active:
                    await transaction.rollback()
                raise

    async def run_bulk(
        self,
        name: str,
        rows: list[dict[str, object]],
        batch_key: str,
        actor: ActorContext,
        *,
        dry_run: bool = False,
        batch_fields: Mapping[str, object] | None = None,
    ) -> Preview | Result:
        """Chunk one batch through :meth:`run`, one atomic transaction per chunk.

        A batch of no rows still runs exactly one chunk, so a command's
        batch-level effects happen whether or not there was anything to iterate.

        ``batch_fields`` carries the input's non-row top-level fields (a bulk
        command's scope, such as ``cycle_id``) into every chunk, so the route
        stage and the in-executor scope check see the same value and the batch
        fingerprint separates identical rows submitted under different scopes.
        """
        spec = self.registry.commands[name]
        if spec.execution_mode != "bulk":
            raise ValueError(f"Command is not registered for bulk execution: {name}")

        fields = dict(batch_fields or {})
        if "rows" in fields or "batch_key" in fields:
            raise ValueError("Batch fields must not restate rows or batch_key")
        batch_input = spec.input_model.model_validate(
            {**fields, "rows": rows, "batch_key": batch_key}
        )
        batch_fingerprint = (
            idempotency.request_fingerprint(batch_input) if not dry_run else None
        )
        completed_chunks: list[int] = []
        combined_rows: list[dict[str, object]] = []
        combined_events: list[Event] = []
        # An empty batch still runs one chunk.  A bulk command may carry a
        # batch-level effect that does not belong to any row -- cancel_job flags
        # the job itself -- and skipping the only transaction would drop it,
        # silently, in exactly the case nobody tests: the batch with no rows.
        offsets = list(range(0, len(rows), 500)) or [0]
        chunk_count = len(offsets)
        batch_audit: dict[str, object] = {
            "subject_type": "bulk_batch",
            "details": {
                "batch_key": batch_key,
                "row_count": len(rows),
                "chunk_count": chunk_count,
            },
        }
        for offset in offsets:
            chunk_number = offset // 500 + 1
            chunk = rows[offset : offset + 500]
            try:
                input_value = spec.input_model.model_validate(
                    {**fields, "rows": chunk, "batch_key": batch_key}
                )
                chunk_result = await self.run(
                    name,
                    input_value,
                    actor,
                    dry_run=dry_run,
                    idempotency_key=None if dry_run else f"{batch_key}:{chunk_number}",
                    _batch_audit=(
                        batch_audit if not dry_run and chunk_number == 1 else None
                    ),
                    _idempotency_fingerprint=batch_fingerprint,
                )
                row_results = chunk_result.summary.get("rows")
                if not isinstance(row_results, list):
                    raise RuntimeError("Bulk command summary must contain a rows list")
                combined_rows.extend(cast(list[dict[str, object]], row_results))
                combined_events.extend(chunk_result.events)
                completed_chunks.append(chunk_number)
            except DomainRejection as error:
                if not completed_chunks:
                    raise
                raise BulkInterrupted(
                    batch_key=batch_key,
                    completed_chunks=completed_chunks,
                    failed_chunk=chunk_number,
                    reasons=error.rejection.reasons,
                ) from error
            except (AuthorizationDenied, RateLimitExceeded):
                # Not a partial failure, so not BulkInterrupted (the design review
                # section 4.23): that exception says "some of your rows did not
                # apply" and hands back resume coordinates, when the truth is
                # that nothing applied and no retry can ever succeed.
                raise
            except Exception as error:
                raise BulkInterrupted(
                    batch_key=batch_key,
                    completed_chunks=completed_chunks,
                    failed_chunk=chunk_number,
                ) from error

        result_type = Preview if dry_run else Result
        return result_type(summary={"rows": combined_rows}, events=combined_events)

    async def _apply_state_ops(self, tx: AsyncSession, operations: list[StateOp]) -> None:
        for index, operation in enumerate(operations, start=1):
            table = Base.metadata.tables.get(operation.model)
            if table is None:
                raise ValueError(f"Unknown state-op model: {operation.model}")
            if operation.op == "insert":
                statement = sa.insert(table).values(**operation.values)
            else:
                if not operation.where:
                    raise ValueError(f"{operation.op} state op requires a where predicate")
                predicate = sa.and_(
                    *(table.c[column] == value for column, value in operation.where.items())
                )
                if operation.op == "update":
                    statement = sa.update(table).where(predicate).values(**operation.values)
                else:
                    statement = sa.delete(table).where(predicate)
            await tx.execute(statement)
            if self.hooks.after_state_op is not None:
                await self.hooks.after_state_op(index)

    async def _append_events(
        self, tx: AsyncSession, events: list[Event], actor: ActorContext
    ) -> None:
        table = Base.metadata.tables["application_events"]
        # the design review 4.41: each INSERT allocates event_seq in Plan.events order.
        # Do not sort, parallelize, or allocate sequence values during decide or
        # preview. Same-application state mutations are serialized by loaders.
        for event in events:
            if event.application_id is None:
                raise ValueError("Application events require application_id")
            await tx.execute(
                sa.insert(table).values(
                    application_id=event.application_id,
                    event_type=event.event_type.value,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    from_round_id=event.from_round,
                    to_round_id=event.to_round,
                    actor_user_id=actor.user_id,
                    reason=event.reason,
                    payload=event.payload,
                )
            )

    async def _write_audit(
        self,
        tx: AsyncSession,
        actor: ActorContext,
        command: str,
        audit: dict[str, object] | None,
    ) -> None:
        if audit is None:
            return
        table = Base.metadata.tables["audit_log"]
        await tx.execute(
            sa.insert(table).values(
                actor_user_id=actor.user_id,
                action=command,
                subject_type=audit.get("subject_type"),
                subject_id=audit.get("subject_id"),
                details=audit.get("details", {}),
            )
        )

    async def _defer(self, tx: AsyncSession, deferred: Deferred) -> None:
        # Procrastinate 3.9.0: this SQL function is the supported in-database defer path.
        # Executing it on this AsyncSession keeps the job in the command transaction.
        await tx.execute(
            sa.text(
                """
                SELECT procrastinate_defer_jobs_v1(
                    ARRAY[
                        ROW(
                            CAST(:queue_name AS varchar),
                            CAST(:task_name AS varchar),
                            CAST(:priority AS integer),
                            CAST(:lock AS text),
                            CAST(:queueing_lock AS text),
                            CAST(:args AS jsonb),
                            CAST(:scheduled_at AS timestamptz)
                        )::procrastinate_job_to_defer_v1
                    ]
                )
                """
            ),
            {
                "queue_name": "default",
                "task_name": deferred.task,
                "priority": 0,
                "lock": None,
                "queueing_lock": None,
                "args": json.dumps(deferred.args),
                "scheduled_at": deferred.schedule_at,
            },
        )
