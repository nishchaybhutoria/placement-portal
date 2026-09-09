"""The event catalog is a contract on producers, not only on templates.

``TEMPLATE_VARIABLES`` says what each event's template may use, and the template
editor reads it to build its variable picker. Nothing checked that the emitter
supplied what the catalog declared, so 94 of the 206 envelopes in the mock D.33
review opened ``Dear ,``: ``render_text`` blanked the missing name and warned,
which is the right fail-open behaviour and is not a substitute for a producer
check.

The check is static. The emitters are pure ``decide`` functions spread across
fourteen modules, several of them parameterised by event key; reaching every one
of them at runtime would cost far more and prove less than reading what they
construct. An emitter whose event key cannot be resolved is a failure too — a
check that quietly skips what it cannot understand rots into a check of nothing.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

from app.modules.notifications.catalog import TEMPLATE_VARIABLES

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
DELIVER_TASK = "deliver_notification"
# The two constructors that carry a notification envelope out of a decide.
EMITTER_CALLS = {"Deferred", "ReminderIntent"}

# Sites that forward an envelope somebody else built, so there is no context
# literal here to check and no event key to resolve. Each is listed by the
# function it sits in, because a line number would rot on the next edit.
PASS_THROUGH = {
    # resend_notification replays a notification_log row as it was stored.
    "_decide_resend",
    # The reminder scans build their contexts as ReminderIntent, which is
    # checked at those construction sites; this fans them out.
    "_decide_reminders",
}


@dataclass(frozen=True, slots=True)
class EmitSite:
    """One construction of a notification envelope in the source."""

    location: str
    event_key_node: ast.expr
    context_keys: frozenset[str]
    function_stack: tuple[str, ...]
    module: Path


@dataclass
class SourceIndex:
    """Everything the resolver needs, gathered in one pass over ``app/``."""

    sites: list[EmitSite] = field(default_factory=list)
    functions: dict[str, ast.FunctionDef] = field(default_factory=dict)
    calls_by_name: dict[str, list[ast.Call]] = field(default_factory=dict)


def _function_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _constant_string(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _literal_keys(node: ast.expr | None) -> frozenset[str]:
    """Literal string keys of a dict display; ``**spread`` entries are invisible."""
    if not isinstance(node, ast.Dict):
        return frozenset()
    return frozenset(
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    )


def _literal_mapping(node: ast.expr) -> dict[str, ast.expr]:
    if not isinstance(node, ast.Dict):
        return {}
    mapping: dict[str, ast.expr] = {}
    for key, value in zip(node.keys, node.values, strict=True):
        name = _constant_string(key) if key is not None else None
        if name is not None:
            mapping[name] = value
    return mapping


def _envelope(call: ast.Call) -> tuple[ast.expr, ast.expr] | None:
    """Return ``(event_key, context)`` nodes if this call emits a notification."""
    name = _function_name(call.func)
    if name not in EMITTER_CALLS:
        return None
    keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
    if name == "Deferred":
        if _constant_string(keywords.get("task")) != DELIVER_TASK:
            return None
        arguments = keywords.get("args")
        if arguments is None:
            return None
        mapping = _literal_mapping(arguments)
        event_key, context = mapping.get("event_key"), mapping.get("context")
    else:
        event_key, context = keywords.get("event_key"), keywords.get("context")
    if event_key is None or context is None:
        return None
    return event_key, context


def _build_index() -> SourceIndex:
    index = SourceIndex()
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _walk(tree, path=path, index=index, stack=())
    return index


def _walk(node: ast.AST, *, path: Path, index: SourceIndex, stack: tuple[str, ...]) -> None:
    for child in ast.iter_child_nodes(node):
        child_stack = stack
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            child_stack = (*stack, child.name)
            if isinstance(child, ast.FunctionDef):
                index.functions[child.name] = child
        if isinstance(child, ast.Call):
            name = _function_name(child.func)
            if name is not None:
                index.calls_by_name.setdefault(name, []).append(child)
            envelope = _envelope(child)
            if envelope is not None:
                event_key, context = envelope
                index.sites.append(
                    EmitSite(
                        location=f"{path.relative_to(APP_ROOT.parent)}:{child.lineno}",
                        event_key_node=event_key,
                        context_keys=_literal_keys(context),
                        function_stack=stack,
                        module=path,
                    )
                )
        _walk(child, path=path, index=index, stack=child_stack)


def _assigned_values(function: ast.FunctionDef, name: str) -> list[ast.expr]:
    values: list[ast.expr] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign) and node.value is not None:
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    values.append(node.value)
    return values


def _parameter_names(function: ast.FunctionDef) -> set[str]:
    arguments = function.args
    return {
        argument.arg
        for argument in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    }


def _parameter_default(function: ast.FunctionDef, name: str) -> ast.expr | None:
    arguments = function.args
    for argument, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True):
        if argument.arg == name and default is not None:
            return default
    positional = [*arguments.posonlyargs, *arguments.args]
    defaults = arguments.defaults
    offset = len(positional) - len(defaults)
    for position, argument in enumerate(positional):
        if argument.arg == name and position >= offset:
            return defaults[position - offset]
    return None


def _from_call_sites(
    index: SourceIndex, function_name: str, parameter: str
) -> dict[str, frozenset[str]] | None:
    """Event keys a parameterised emitter can carry, with per-call-site extras.

    ``plan_decline`` is the shape this exists for: one envelope construction,
    two event keys, and a caller that contributes the variable the second one
    declares through ``notification_context_extra``.
    """
    function = index.functions.get(function_name)
    if function is None:
        return None
    resolved: dict[str, frozenset[str]] = {}
    default = _parameter_default(function, parameter)
    positional = [*function.args.posonlyargs, *function.args.args]
    position = next(
        (index_ for index_, argument in enumerate(positional) if argument.arg == parameter),
        None,
    )
    for call in index.calls_by_name.get(function_name, []):
        keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg}
        supplied = keywords.get(parameter, default)
        if position is not None and position < len(call.args):
            supplied = call.args[position]
        if supplied is None:
            return None
        if isinstance(supplied, ast.Constant) and supplied.value is None:
            continue  # An explicit "this transition sends nothing".
        event_key = _constant_string(supplied)
        if event_key is None:
            return None
        extras: set[str] = set()
        for name, value in keywords.items():
            if name != parameter and isinstance(value, ast.Dict):
                extras |= _literal_keys(value)
        resolved[event_key] = resolved.get(event_key, frozenset()) | frozenset(extras)
    return resolved or None


def _resolve(site: EmitSite, index: SourceIndex) -> dict[str, frozenset[str]] | None:
    """Event keys this site can emit, mapped to context keys added by its callers."""
    node = site.event_key_node
    literal = _constant_string(node)
    if literal is not None:
        return {literal: frozenset()}
    if isinstance(node, ast.IfExp):
        branches = [_constant_string(node.body), _constant_string(node.orelse)]
        if all(branch is not None for branch in branches):
            return {branch: frozenset() for branch in branches if branch is not None}
        return None
    if not isinstance(node, ast.Name):
        return None

    for function_name in reversed(site.function_stack):
        function = index.functions.get(function_name)
        if function is None:
            continue
        if node.id in _parameter_names(function):
            return _from_call_sites(index, function_name, node.id)
        assigned = _assigned_values(function, node.id)
        if assigned:
            resolved: dict[str, frozenset[str]] = {}
            for value in assigned:
                if isinstance(value, ast.IfExp):
                    candidates = [_constant_string(value.body), _constant_string(value.orelse)]
                else:
                    candidates = [_constant_string(value)]
                if any(candidate is None for candidate in candidates):
                    return None
                for candidate in candidates:
                    if candidate is not None:
                        resolved[candidate] = frozenset()
            return resolved
    return None


def test_every_emitter_supplies_the_variables_its_event_key_declares() -> None:
    index = _build_index()
    assert index.sites, "found no notification emitters; the detector is broken"

    failures: list[str] = []
    for site in sorted(index.sites, key=lambda item: item.location):
        if PASS_THROUGH.intersection(site.function_stack):
            continue
        resolved = _resolve(site, index)
        if resolved is None:
            failures.append(f"{site.location}: could not resolve the event key of this emitter")
            continue
        for event_key, extras in sorted(resolved.items()):
            declared = TEMPLATE_VARIABLES.get(event_key)
            if declared is None:
                failures.append(f"{site.location}: emits unknown event key {event_key!r}")
                continue
            supplied = site.context_keys | extras
            missing = [variable for variable in declared if variable not in supplied]
            if missing:
                failures.append(
                    f"{site.location}: {event_key} declares {', '.join(missing)}"
                    " but the emitter does not supply it"
                )

    assert not failures, "Notification emitters do not honour the catalog:\n" + "\n".join(
        failures
    )


def test_the_contract_check_sees_every_declared_event_key_that_has_an_emitter() -> None:
    """A resolver that silently stopped matching would make the test above vacuous."""
    index = _build_index()
    emitted: set[str] = set()
    for site in index.sites:
        if PASS_THROUGH.intersection(site.function_stack):
            continue
        resolved = _resolve(site, index)
        if resolved is not None:
            emitted |= set(resolved)

    assert emitted == set(TEMPLATE_VARIABLES)
