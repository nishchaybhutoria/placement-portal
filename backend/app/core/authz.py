"""Registry-driven route and loaded-state authorization for IDN-3."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel

from app.core.errors import CYCLE_ARCHIVED, AuthorizationDenied, DomainRejection
from app.core.plan import ActorContext, LoadedState, Reason, Rejection, ScopeIds
from app.core.registry import CommandSpec, ScreenSpec

#: CYC-1 freezes domain mutations, not reads.  Keep the exception explicit:
#: archived seasons are the seasons NIRF and RTI filings need to inspect, and
#: blocking their export invites production SQL (the design review section 4.31).
ARCHIVED_CYCLE_COMMAND_ALLOWLIST = frozenset({"request_export"})


def require_staff_cycle(actor: ActorContext, cycle_id: UUID) -> None:
    """A coordinator sees their own cycles; an administrator sees every one.

    The registry's ``roles=("staff",)`` only asks whether the caller coordinates
    *something* -- it cannot know which cycle a screen is about, because that is
    a path parameter the screen resolves.  Every cycle-scoped staff screen must
    therefore repeat the question here, exactly as ``_check_loaded_scope`` does
    for every cycle-scoped staff command (CONTRIBUTING.md invariant 8).
    """
    if actor.role != "admin" and cycle_id not in actor.coordinated_cycle_ids:
        raise AuthorizationDenied(authenticated=actor.user_id is not None)


class Authorizer:
    """Apply typed actor policy before loading and repeat it against loaded scope."""

    def check(
        self, spec: CommandSpec, actor: ActorContext, input_value: BaseModel
    ) -> None:
        if not self._actor_allowed(spec, actor):
            raise AuthorizationDenied(authenticated=actor.user_id is not None)
        if spec.actor == "staff" and spec.scope == "cycle" and actor.role != "admin":
            cycle_id = getattr(input_value, "cycle_id", None)
            if isinstance(cycle_id, UUID) and cycle_id not in actor.coordinated_cycle_ids:
                raise AuthorizationDenied(authenticated=True)

    def check_scope(
        self, spec: CommandSpec, actor: ActorContext, state: LoadedState
    ) -> None:
        """Re-check authorization against the state the loader actually read."""
        if (
            spec.scope == "cycle"
            and spec.name not in ARCHIVED_CYCLE_COMMAND_ALLOWLIST
        ):
            self._check_cycle_not_archived(spec, state)
        self._check_loaded_scope(spec, actor, state.scope_ids)

    def check_replayed_scope(
        self, spec: CommandSpec, actor: ActorContext, scope_ids: ScopeIds
    ) -> None:
        """Re-check scope for a cached idempotency replay.

        A replay loads nothing and writes nothing: it returns the result the
        original command already committed.  The caller must still be in scope,
        but the CYC-1 archival check deliberately does not run here — an
        archival that happened after the original command cannot retroactively
        invalidate a result that is only being read back.  The exemption is
        stated here, on the one branch it applies to, rather than by handing
        ``check_scope`` a synthetic state that claims to be unarchived.
        """
        self._check_loaded_scope(spec, actor, scope_ids)

    def _check_loaded_scope(
        self, spec: CommandSpec, actor: ActorContext, scope_ids: ScopeIds
    ) -> None:
        if not self._actor_allowed(spec, actor):
            raise AuthorizationDenied(authenticated=actor.user_id is not None)
        if spec.actor == "student":
            enrollment_id = scope_ids.enrollment_id
            if (
                enrollment_id is not None
                and enrollment_id != actor.current_enrollment_id
            ):
                raise AuthorizationDenied(authenticated=True)
        if spec.actor == "staff" and spec.scope == "cycle" and actor.role != "admin":
            cycle_id = scope_ids.cycle_id
            if cycle_id is None or cycle_id not in actor.coordinated_cycle_ids:
                raise AuthorizationDenied(authenticated=True)

    @staticmethod
    def _check_cycle_not_archived(spec: CommandSpec, state: LoadedState) -> None:
        """Reject archived-cycle mutations (Behavior CYC-1, LLD section 9.3).

        The check lives here, beside the scope check, so every cycle-scoped
        command inherits it rather than restating it in each ``decide``.  The
        caller consults ``ARCHIVED_CYCLE_COMMAND_ALLOWLIST`` first for explicit
        read operations.  Every other cycle-scoped state must report the flag:
        fail closed so a later milestone cannot forget it.
        """
        archived = getattr(state, "cycle_archived", None)
        if archived is None:
            raise RuntimeError(
                f"Cycle-scoped command {spec.name} loaded a state without cycle_archived"
            )
        if archived:
            raise DomainRejection(
                Rejection(
                    reasons=[
                        Reason(
                            code=CYCLE_ARCHIVED,
                            human="The cycle is archived and is now read-only",
                            path="cycle_id",
                        )
                    ]
                )
            )

    def check_screen(self, spec: ScreenSpec, actor: ActorContext) -> None:
        """Authorize a generated read screen from its registry role metadata."""
        authenticated = actor.user_id is not None and actor.session_id is not None
        allowed = (
            ("anonymous" in spec.roles)
            or ("test" in spec.roles and actor.is_test_harness)
            or ("authenticated" in spec.roles and authenticated)
            or (
                "student" in spec.roles
                and authenticated
                and actor.role == "student"
                and actor.current_enrollment_id is not None
            )
            or (
                "staff" in spec.roles
                and authenticated
                and (actor.role == "admin" or bool(actor.coordinated_cycle_ids))
            )
            or ("admin" in spec.roles and authenticated and actor.role == "admin")
        )
        if not allowed:
            raise AuthorizationDenied(authenticated=authenticated)

    @staticmethod
    def _actor_allowed(spec: CommandSpec, actor: ActorContext) -> bool:
        if spec.actor == "anonymous":
            return True
        if spec.actor == "system":
            return actor.is_system
        if spec.actor == "test":
            return actor.is_test_harness
        authenticated = actor.user_id is not None and actor.session_id is not None
        if spec.actor == "authenticated":
            return authenticated
        if spec.actor == "student":
            return (
                authenticated
                and actor.role == "student"
                and actor.current_enrollment_id is not None
            )
        if spec.actor == "admin":
            return authenticated and actor.role == "admin"
        if spec.actor == "admin_or_system":
            return actor.is_system or (authenticated and actor.role == "admin")
        if spec.actor == "staff":
            return authenticated and (
                actor.role == "admin" or bool(actor.coordinated_cycle_ids)
            )
        return False
