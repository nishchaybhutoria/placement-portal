"""Executor-backed login provisioning and session establishment for IDN-1/2/3."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, PrivateAttr
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    INACTIVE_USER,
    OAUTH_STATE_EXPIRED,
    OAUTH_STATE_INVALID,
    OUTSIDE_ALLOWED_DOMAIN,
)
from app.core.plan import (
    ActorContext,
    Plan,
    Reason,
    Rejection,
    ScopeIds,
    StateOp,
)
from app.core.registry import Registry
from app.settings import Settings

DEFAULT_SESSION_HOURS = 24
OAUTH_STATE_LIFETIME = timedelta(minutes=10)
OAUTH_STATE_PREFIX = "oauth-state:v1:"
OAUTH_STATE_PURGE_BATCH = 100


class SessionEstablishInput(BaseModel):
    """Base input whose secret material is private to Pydantic serialization."""
    model_config = ConfigDict(extra="forbid")


    email: str

    _full_name: str = PrivateAttr()
    _session_token: str = PrivateAttr()
    _session_secret: str = PrivateAttr()
    _issued_at: datetime = PrivateAttr()
    _new_user_id: UUID = PrivateAttr()
    _new_enrollment_id: UUID = PrivateAttr()
    _new_session_id: UUID = PrivateAttr()
    _prior_session_id: UUID | None = PrivateAttr(default=None)
    _allowed_domain: str = PrivateAttr()

    def prepare(
        self,
        *,
        full_name: str,
        settings: Settings,
        prior_session_id: UUID | None = None,
        issued_at: datetime | None = None,
    ) -> None:
        self._full_name = full_name
        self._session_token = secrets.token_urlsafe(32)
        self._session_secret = settings.session_secret
        self._issued_at = issued_at or datetime.now(UTC)
        self._new_user_id = uuid4()
        self._new_enrollment_id = uuid4()
        self._new_session_id = uuid4()
        self._prior_session_id = prior_session_id
        self._allowed_domain = settings.allowed_domain

    @property
    def session_token(self) -> str:
        return self._session_token


class GoogleLoginInput(SessionEstablishInput):
    full_name: str


class DevLoginInput(SessionEstablishInput):
    pass


class LoginSummary(BaseModel):
    authenticated: bool
    email: str


class OAuthStateInput(BaseModel):
    """Private hashed OAuth nonce input; raw state is never a Pydantic field."""
    model_config = ConfigDict(extra="forbid")


    _key: str = PrivateAttr()
    _now: datetime = PrivateAttr()
    _expires_at: datetime = PrivateAttr()
    _superseded_keys: tuple[str, ...] = PrivateAttr(default=())

    def prepare(
        self,
        *,
        state: str,
        settings: Settings,
        now: datetime | None = None,
        superseded_keys: tuple[str, ...] = (),
    ) -> None:
        issued_at = now or datetime.now(UTC)
        self._key = oauth_state_key(state, settings.session_secret)
        self._now = issued_at
        self._expires_at = issued_at + OAUTH_STATE_LIFETIME
        self._superseded_keys = tuple(
            sorted(
                dict.fromkeys(
                    key for key in superseded_keys if key.startswith(OAUTH_STATE_PREFIX)
                )
            )
        )


class IssueOAuthStateSummary(BaseModel):
    issued: bool


class ConsumeOAuthStateSummary(BaseModel):
    consumed: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class LoginState:
    scope_ids: ScopeIds
    user_id: UUID | None
    user_is_active: bool | None
    prior_session_id: UUID | None
    session_hours: int
    hook_state: tuple[tuple[str, object], ...] = ()

    def hook(self, name: str) -> object:
        """Return the state a post-login hook loaded inside the login transaction."""
        for key, value in self.hook_state:
            if key == name:
                return value
        return None


@dataclass(frozen=True, slots=True)
class OAuthStateRecord:
    scope_ids: ScopeIds
    key: str
    command: str | None = None
    result: dict[str, object] | None = None
    delete_keys: tuple[str, ...] = ()
    superseded_complete: bool = True


class LoginInput(Protocol):
    email: str
    _full_name: str
    _session_token: str
    _session_secret: str
    _issued_at: datetime
    _new_user_id: UUID
    _new_enrollment_id: UUID
    _new_session_id: UUID
    _prior_session_id: UUID | None
    _allowed_domain: str


PostLoginPlanner = Callable[[LoginInput, LoginState, ActorContext], list[StateOp]]
PostLoginLoader = Callable[..., Awaitable[object]]


@dataclass(frozen=True, slots=True)
class PostLoginHook:
    name: str
    planner: PostLoginPlanner
    loader: PostLoginLoader | None


class PostLoginHooks:
    """Ordered login hooks: each may load inside the transaction, then plan purely."""

    def __init__(self) -> None:
        self._hooks: list[PostLoginHook] = []

    def register(
        self,
        planner: PostLoginPlanner,
        *,
        name: str | None = None,
        loader: PostLoginLoader | None = None,
    ) -> None:
        """Register (or replace, by name) one hook; registration is idempotent."""
        hook = PostLoginHook(
            name=name or getattr(planner, "__name__", str(len(self._hooks))),
            planner=planner,
            loader=loader,
        )
        for index, existing in enumerate(self._hooks):
            if existing.name == hook.name:
                self._hooks[index] = hook
                return
        self._hooks.append(hook)

    async def load(
        self, tx: AsyncSession, email: str, *, lock: bool
    ) -> tuple[tuple[str, object], ...]:
        loaded: list[tuple[str, object]] = []
        for hook in self._hooks:
            if hook.loader is None:
                continue
            loaded.append((hook.name, await hook.loader(tx, email, lock=lock)))
        return tuple(loaded)

    def plan(
        self, input_value: LoginInput, state: LoginState, actor: ActorContext
    ) -> list[StateOp]:
        operations: list[StateOp] = []
        for hook in self._hooks:
            operations.extend(hook.planner(input_value, state, actor))
        return operations


post_login_hooks = PostLoginHooks()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def email_matches_domain(email: str, allowed_domain: str) -> bool:
    local, separator, domain = normalize_email(email).rpartition("@")
    return bool(local and separator and domain == allowed_domain.strip().casefold())


def hash_session_token(token: str, secret: str) -> str:
    return hmac.new(secret.encode(), token.encode(), hashlib.sha256).hexdigest()


def oauth_state_key(state: str, secret: str) -> str:
    return f"{OAUTH_STATE_PREFIX}{hash_session_token(state, secret)}"


def new_oauth_state_input(
    *,
    state: str,
    settings: Settings,
    now: datetime | None = None,
    superseded_keys: tuple[str, ...] = (),
) -> OAuthStateInput:
    input_value = OAuthStateInput()
    input_value.prepare(
        state=state,
        settings=settings,
        now=now,
        superseded_keys=superseded_keys,
    )
    return input_value


def new_login_input(
    *,
    email: str,
    full_name: str,
    settings: Settings,
    prior_session_id: UUID | None = None,
    issued_at: datetime | None = None,
) -> GoogleLoginInput:
    input_value = GoogleLoginInput(email=normalize_email(email), full_name=full_name)
    input_value.prepare(
        full_name=full_name,
        settings=settings,
        prior_session_id=prior_session_id,
        issued_at=issued_at,
    )
    return input_value


def prepare_dev_login_input(
    input_value: DevLoginInput,
    *,
    settings: Settings,
    prior_session_id: UUID | None,
) -> DevLoginInput:
    normalized = normalize_email(input_value.email)
    prepared = DevLoginInput(email=normalized)
    local = normalized.partition("@")[0]
    full_name = " ".join(part.capitalize() for part in local.replace(".", " ").split())
    prepared.prepare(
        full_name=full_name or local,
        settings=settings,
        prior_session_id=prior_session_id,
    )
    return prepared


async def _load_login(
    tx: AsyncSession,
    input_value: BaseModel,
    *,
    lock: bool,
    hooks: PostLoginHooks | None = None,
) -> LoginState:
    if not isinstance(input_value, SessionEstablishInput):
        raise TypeError("Login loader requires SessionEstablishInput")
    email = normalize_email(input_value.email)
    await tx.execute(
        sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:email, 0))"),
        {"email": email},
    )
    user_row = (
        await tx.execute(
            sa.text("SELECT id, is_active FROM users WHERE email = :email"),
            {"email": email},
        )
    ).mappings().one_or_none()
    setting_row = (
        await tx.execute(
            sa.text("SELECT value FROM settings WHERE key = 'session_hours'")
        )
    ).one_or_none()
    session_hours = DEFAULT_SESSION_HOURS
    if setting_row is not None:
        setting_value = setting_row[0]
        if isinstance(setting_value, bool) or not isinstance(setting_value, int):
            raise ValueError("settings.session_hours must be a positive integer")
        if setting_value <= 0:
            raise ValueError("settings.session_hours must be a positive integer")
        session_hours = setting_value
    prior_session_id: UUID | None = None
    if input_value._prior_session_id is not None:
        statement = sa.text(
            "SELECT id FROM sessions WHERE id = :id AND revoked_at IS NULL "
            "AND expires_at > :issued_at"
            + (" FOR UPDATE" if lock else "")
        )
        prior_session_id = await tx.scalar(
            statement,
            {
                "id": input_value._prior_session_id,
                "issued_at": input_value._issued_at,
            },
        )
    hook_state = (
        await hooks.load(tx, email, lock=lock) if hooks is not None else ()
    )
    return LoginState(
        scope_ids=ScopeIds(),
        user_id=user_row["id"] if user_row is not None else None,
        user_is_active=user_row["is_active"] if user_row is not None else None,
        prior_session_id=prior_session_id,
        session_hours=session_hours,
        hook_state=hook_state,
    )


def _decide_login_with_hooks(
    hooks: PostLoginHooks,
) -> Callable[[BaseModel, object, object, object, ActorContext], Plan | Rejection]:
    def decide(
        input_model: BaseModel,
        loaded_state: object,
        _policy: object,
        _overrides: object,
        actor: ActorContext,
    ) -> Plan | Rejection:
        """Establish an institute session and provision first login per IDN-1/2/3."""
        if not isinstance(input_model, SessionEstablishInput):
            raise TypeError("Login decider requires SessionEstablishInput")
        if not isinstance(loaded_state, LoginState):
            raise TypeError("Login decider requires LoginState")
        input_value: LoginInput = input_model
        if not email_matches_domain(input_value.email, input_value._allowed_domain):
            return Rejection(
                reasons=[
                    Reason(
                        code=OUTSIDE_ALLOWED_DOMAIN,
                        human="Use an email from the allowed institute domain",
                        path="email",
                    )
                ]
            )
        if loaded_state.user_is_active is False:
            return Rejection(
                reasons=[
                    Reason(
                        code=INACTIVE_USER,
                        human="This user account is inactive",
                        path="email",
                    )
                ]
            )

        user_id = loaded_state.user_id or input_value._new_user_id
        operations: list[StateOp] = []
        if loaded_state.user_id is None:
            operations.extend(
                [
                    StateOp(
                        op="insert",
                        model="users",
                        values={
                            "id": user_id,
                            "email": normalize_email(input_value.email),
                            "full_name": input_value._full_name,
                        },
                    ),
                    StateOp(
                        op="insert",
                        model="enrollments",
                        values={
                            "id": input_value._new_enrollment_id,
                            "user_id": user_id,
                            "is_current": True,
                            "roll_number": None,
                        },
                    ),
                ]
            )
        if loaded_state.prior_session_id is not None:
            operations.append(
                StateOp(
                    op="update",
                    model="sessions",
                    values={"revoked_at": input_value._issued_at},
                    where={"id": loaded_state.prior_session_id},
                )
            )
        operations.append(
            StateOp(
                op="insert",
                model="sessions",
                values={
                    "id": input_value._new_session_id,
                    "token_hash": hash_session_token(
                        input_value._session_token, input_value._session_secret
                    ),
                    "user_id": user_id,
                    "expires_at": input_value._issued_at
                    + timedelta(hours=loaded_state.session_hours),
                    "revoked_at": None,
                },
            )
        )
        operations.extend(hooks.plan(input_value, loaded_state, actor))
        return Plan(
            state_ops=operations,
            events=[],
            deferred=[],
            audit={
                "subject_type": "user",
                "subject_id": user_id,
                "details": {"email": normalize_email(input_value.email)},
            },
            summary={
                "authenticated": True,
                "email": normalize_email(input_value.email),
            },
        )

    return decide


async def _load_oauth_state_issue(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> OAuthStateRecord:
    if not isinstance(input_value, OAuthStateInput):
        raise TypeError("OAuth state issue requires OAuthStateInput")
    superseded_keys: tuple[str, ...] = ()
    if input_value._superseded_keys:
        superseded_keys = tuple(
            str(key)
            for key in (
                await tx.execute(
                    sa.text(
                        "SELECT key FROM idempotency_keys "
                        "WHERE command = 'issue_oauth_state' "
                        "AND key = ANY(CAST(:keys AS text[])) "
                        "ORDER BY key" + (" FOR UPDATE" if lock else "")
                    ),
                    {"keys": list(input_value._superseded_keys)},
                )
            ).scalars()
        )
        if superseded_keys != input_value._superseded_keys:
            return OAuthStateRecord(
                scope_ids=ScopeIds(),
                key=input_value._key,
                delete_keys=superseded_keys,
                superseded_complete=False,
            )
    purge_lock_clause = " FOR UPDATE SKIP LOCKED" if lock else ""
    expired_keys = (
        await tx.execute(
            sa.text(
                "SELECT key FROM idempotency_keys "
                "WHERE command = 'issue_oauth_state' "
                "AND key LIKE :key_prefix "
                "AND NOT (key = ANY(CAST(:exact_keys AS text[]))) "
                "AND result ->> 'kind' = 'oauth_state' "
                "AND result ->> 'expires_at' IS NOT NULL "
                "AND CAST(result ->> 'expires_at' AS timestamptz) <= :now "
                "ORDER BY key LIMIT :batch_size" + purge_lock_clause
            ),
            {
                "key_prefix": f"{OAUTH_STATE_PREFIX}%",
                "exact_keys": list(input_value._superseded_keys),
                "now": input_value._now,
                "batch_size": OAUTH_STATE_PURGE_BATCH,
            },
        )
    ).scalars().all()
    delete_keys = tuple(dict.fromkeys((*superseded_keys, *expired_keys)))
    return OAuthStateRecord(
        scope_ids=ScopeIds(), key=input_value._key, delete_keys=delete_keys
    )


async def _load_oauth_state_consume(
    tx: AsyncSession, input_value: BaseModel, *, lock: bool
) -> OAuthStateRecord:
    if not isinstance(input_value, OAuthStateInput):
        raise TypeError("OAuth state consume requires OAuthStateInput")
    statement = sa.text(
        "SELECT command, result FROM idempotency_keys WHERE key = :key"
        + (" FOR UPDATE" if lock else "")
    )
    row = (
        await tx.execute(statement, {"key": input_value._key})
    ).mappings().one_or_none()
    return OAuthStateRecord(
        scope_ids=ScopeIds(),
        key=input_value._key,
        command=row["command"] if row is not None else None,
        result=row["result"] if row is not None else None,
    )


def _decide_issue_oauth_state(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Persist a hashed, expiring Google OAuth nonce for IDN-1."""
    if not isinstance(input_value, OAuthStateInput):
        raise TypeError("OAuth state issue requires OAuthStateInput")
    if not isinstance(state, OAuthStateRecord):
        raise TypeError("OAuth state issue requires OAuthStateRecord")
    if input_value._superseded_keys and not state.superseded_complete:
        return Rejection(
            reasons=[
                Reason(
                    code=OAUTH_STATE_INVALID,
                    human="OAuth state was superseded by another login start",
                )
            ]
        )
    return Plan(
        state_ops=[
            *(
                StateOp(
                    op="delete",
                    model="idempotency_keys",
                    values={},
                    where={"key": key},
                )
                for key in state.delete_keys
            ),
            StateOp(
                op="insert",
                model="idempotency_keys",
                values={
                    "key": state.key,
                    "command": "issue_oauth_state",
                    "result": {
                        "kind": "oauth_state",
                        "expires_at": input_value._expires_at.isoformat(),
                    },
                },
            )
        ],
        events=[],
        deferred=[],
        audit=None,
        summary={"issued": True},
    )


def _decide_consume_oauth_state(
    input_value: BaseModel,
    state: object,
    _policy: object,
    _overrides: object,
    _actor: ActorContext,
) -> Plan | Rejection:
    """Atomically consume one server-side Google OAuth nonce for IDN-1."""
    if not isinstance(input_value, OAuthStateInput):
        raise TypeError("OAuth state consume requires OAuthStateInput")
    if not isinstance(state, OAuthStateRecord):
        raise TypeError("OAuth state consume requires OAuthStateRecord")
    if state.command != "issue_oauth_state" or not isinstance(state.result, dict):
        return Rejection(
            reasons=[
                Reason(
                    code=OAUTH_STATE_INVALID,
                    human="OAuth state is missing or was already consumed",
                )
            ]
        )
    raw_expiry = state.result.get("expires_at")
    try:
        expires_at = datetime.fromisoformat(raw_expiry) if isinstance(raw_expiry, str) else None
    except ValueError:
        expires_at = None
    if expires_at is None:
        return Rejection(
            reasons=[
                Reason(code=OAUTH_STATE_INVALID, human="OAuth state metadata is invalid")
            ]
        )
    reason = OAUTH_STATE_EXPIRED if expires_at <= input_value._now else None
    return Plan(
        state_ops=[
            StateOp(op="delete", model="idempotency_keys", values={}, where={"key": state.key})
        ],
        events=[],
        deferred=[],
        audit=None,
        summary={"consumed": reason is None, "reason": reason},
    )


def register_identity_commands(
    registry: Registry,
    *,
    settings: Settings,
    hooks: PostLoginHooks | None = None,
) -> None:
    planners = hooks or post_login_hooks
    decide = _decide_login_with_hooks(planners)

    async def login_loader(
        tx: AsyncSession, input_value: BaseModel, *, lock: bool
    ) -> LoginState:
        return await _load_login(tx, input_value, lock=lock, hooks=planners)

    registry.command(
        name="issue_oauth_state",
        input_model=OAuthStateInput,
        output_model=IssueOAuthStateSummary,
        actor="system",
        scope="none",
        loader=_load_oauth_state_issue,
        rule_domains=(),
        spec_ids=("IDN-1",),
        expose_http=False,
    )(_decide_issue_oauth_state)
    registry.command(
        name="consume_oauth_state",
        input_model=OAuthStateInput,
        output_model=ConsumeOAuthStateSummary,
        actor="system",
        scope="none",
        loader=_load_oauth_state_consume,
        rule_domains=(),
        spec_ids=("IDN-1",),
        expose_http=False,
    )(_decide_consume_oauth_state)
    registry.command(
        name="google_login",
        input_model=GoogleLoginInput,
        output_model=LoginSummary,
        actor="system",
        scope="none",
        loader=login_loader,
        rule_domains=(),
        spec_ids=("IDN-1", "IDN-2", "IDN-3"),
        expose_http=False,
        session_effect="establish",
    )(decide)
    if settings.dev_login:
        registry.command(
            name="dev_login",
            input_model=DevLoginInput,
            output_model=LoginSummary,
            actor="anonymous",
            scope="none",
            loader=login_loader,
            rule_domains=(),
            spec_ids=("IDN-1", "IDN-2", "IDN-3"),
            session_effect="establish",
        )(decide)
