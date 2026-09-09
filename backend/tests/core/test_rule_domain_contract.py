"""Static contract between command declarations and override-aware gates.

The executor resolves only ``CommandSpec.rule_domains``.  A loader or decider
that consults another domain therefore makes a real grant silently inert, while
a stale declaration makes audit evidence claim a gate participated when it did
not.  Follow the registered loader/decider call graph and require both sets to
match.
"""

from __future__ import annotations

import ast
import importlib.util
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from types import FunctionType

from app.bootstrap import build_registry
from app.domain.gates import GATE_DOMAINS
from app.domain.shared import RuleDomain

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
GATES_MODULE = "app.domain.gates"
type FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True, slots=True)
class Symbol:
    module: str
    name: str | None


@dataclass(frozen=True, slots=True)
class FunctionSource:
    module: str
    path: Path
    node: FunctionNode

    @property
    def key(self) -> tuple[str, int]:
        return self.module, self.node.lineno


@dataclass(slots=True)
class ModuleSource:
    path: Path
    tree: ast.Module
    imports: dict[str, Symbol] = field(default_factory=dict)
    functions: dict[str, list[FunctionSource]] = field(
        default_factory=lambda: defaultdict(list)
    )
    top_level_names: set[str] = field(default_factory=set)


class BodyVisitor(ast.NodeVisitor):
    """Visit one function body without attributing nested function bodies to it."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []
        self.domains: set[RuleDomain] = set()

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast API
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802 - ast API
        if isinstance(node.value, ast.Name) and node.value.id == "RuleDomain":
            try:
                self.domains.add(RuleDomain[node.attr])
            except KeyError:
                pass
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        del node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        del node

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        del node

    def inspect(self, function: FunctionNode) -> None:
        for statement in function.body:
            self.visit(statement)


class SourceIndex:
    def __init__(self) -> None:
        self.modules: dict[str, ModuleSource] = {}
        self.functions_by_line: dict[tuple[str, int], FunctionSource] = {}
        self._build()

    def _build(self) -> None:
        for path in sorted(APP_ROOT.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = path.relative_to(APP_ROOT).with_suffix("")
            parts = relative.parts
            if parts[-1] == "__init__":
                parts = parts[:-1]
            module_name = ".".join(("app", *parts))
            tree = ast.parse(path.read_text(encoding="utf-8"))
            self.modules[module_name] = ModuleSource(path=path, tree=tree)

        # Imports can name a child module, so index them only after every module
        # name exists; source order must not decide whether a call resolves.
        for module_name, module in self.modules.items():
            self._index_top_level(module_name, module)
            for node in ast.walk(module.tree):
                if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    continue
                source = FunctionSource(module_name, module.path, node)
                module.functions[node.name].append(source)
                self.functions_by_line[source.key] = source

    def _index_top_level(self, module_name: str, module: ModuleSource) -> None:
        package = module_name.rpartition(".")[0]
        for node in module.tree.body:
            if isinstance(node, ast.Import):
                for item in node.names:
                    local = item.asname or item.name.split(".")[0]
                    imported = item.name if item.asname else item.name.split(".")[0]
                    module.imports[local] = Symbol(imported, None)
                    module.top_level_names.add(local)
            elif isinstance(node, ast.ImportFrom):
                imported_module = node.module or ""
                if node.level:
                    imported_module = importlib.util.resolve_name(
                        f"{'.' * node.level}{imported_module}", package
                    )
                for item in node.names:
                    if item.name == "*":
                        continue
                    local = item.asname or item.name
                    child_module = f"{imported_module}.{item.name}"
                    if child_module in self.modules:
                        module.imports[local] = Symbol(child_module, None)
                    else:
                        module.imports[local] = Symbol(imported_module, item.name)
                    module.top_level_names.add(local)
            elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                module.top_level_names.add(node.name)
            elif isinstance(node, ast.Assign):
                module.top_level_names.update(
                    target.id for target in node.targets if isinstance(target, ast.Name)
                )
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                module.top_level_names.add(node.target.id)

    def runtime_source(self, function: object) -> FunctionSource:
        assert isinstance(function, FunctionType), f"unsupported command callable {function!r}"
        module_name = function.__module__
        by_line = self.functions_by_line.get((module_name, function.__code__.co_firstlineno))
        if by_line is not None:
            return by_line
        candidates = self.modules[module_name].functions.get(function.__name__, [])
        assert len(candidates) == 1, (
            f"cannot resolve {module_name}.{function.__qualname__} to one source function"
        )
        return candidates[0]

    def _symbol_source(
        self, symbol: Symbol, *, seen: frozenset[tuple[str, str]] = frozenset()
    ) -> FunctionSource | None:
        if symbol.name is None:
            return None
        marker = (symbol.module, symbol.name)
        if marker in seen:
            return None
        module = self.modules.get(symbol.module)
        if module is None:
            return None
        candidates = module.functions.get(symbol.name, [])
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            locations = ", ".join(str(item.node.lineno) for item in candidates)
            raise AssertionError(
                f"ambiguous source for {symbol.module}.{symbol.name} at lines {locations}"
            )
        forwarded = module.imports.get(symbol.name)
        if forwarded is not None:
            return self._symbol_source(forwarded, seen=seen | {marker})
        if symbol.name not in module.top_level_names:
            raise AssertionError(
                f"cannot resolve app call {symbol.module}.{symbol.name}"
            )
        # A known class or callable constant is not a function-call edge.
        return None

    def resolve_call(self, source: FunctionSource, call: ast.Call) -> FunctionSource | None:
        module = self.modules[source.module]
        if isinstance(call.func, ast.Name):
            candidates = module.functions.get(call.func.id, [])
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                locations = ", ".join(str(item.node.lineno) for item in candidates)
                raise AssertionError(
                    f"{source.path}:{call.lineno}: ambiguous local call "
                    f"{call.func.id} (definitions at {locations})"
                )
            imported = module.imports.get(call.func.id)
            return self._symbol_source(imported) if imported is not None else None

        if (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
        ):
            imported = module.imports.get(call.func.value.id)
            if imported is not None and imported.name is None:
                return self._symbol_source(Symbol(imported.module, call.func.attr))
        # Calls on values (``tx.execute``, enum constructors, dataclasses) do not
        # add domain behavior.  App function calls through imports are resolved
        # above; an ambiguity there is a hard failure rather than a silent skip.
        return None

    def domains_for(self, *roots: object) -> frozenset[RuleDomain]:
        domains: set[RuleDomain] = set()
        visited: set[tuple[str, int]] = set()

        def walk(source: FunctionSource) -> None:
            if source.key in visited:
                return
            visited.add(source.key)
            visitor = BodyVisitor()
            visitor.inspect(source.node)
            domains.update(visitor.domains)
            for call in visitor.calls:
                target = self.resolve_call(source, call)
                if target is None:
                    continue
                if target.module == GATES_MODULE and target.node.name in GATE_DOMAINS:
                    domains.update(GATE_DOMAINS[target.node.name])
                else:
                    walk(target)

        for root in roots:
            walk(self.runtime_source(root))
        return frozenset(domains)


def _gate_override_consumers(index: SourceIndex) -> set[str]:
    """Every gate function that can reach an override-selection primitive."""
    module = index.modules[GATES_MODULE]
    calls: dict[str, set[str]] = {}
    for name, candidates in module.functions.items():
        if len(candidates) != 1:
            continue
        visitor = BodyVisitor()
        visitor.inspect(candidates[0].node)
        calls[name] = {
            target.node.name
            for call in visitor.calls
            if (target := index.resolve_call(candidates[0], call)) is not None
            and target.module == GATES_MODULE
        }

    primitives = {"_append_override_decision", "_selected_override"}
    consumers = {name for name, targets in calls.items() if targets & primitives}
    while True:
        expanded = consumers | {
            name for name, targets in calls.items() if targets & consumers
        }
        if expanded == consumers:
            return consumers
        consumers = expanded


def test_every_override_aware_gate_is_in_the_domain_catalog() -> None:
    index = SourceIndex()
    consumers = _gate_override_consumers(index)
    assert consumers == set(GATE_DOMAINS), (
        "GATE_DOMAINS must name exactly the functions that can select an override; "
        f"missing={sorted(consumers - set(GATE_DOMAINS))}, "
        f"stale={sorted(set(GATE_DOMAINS) - consumers)}"
    )


def test_commands_declare_exactly_the_domains_their_code_can_consult() -> None:
    index = SourceIndex()
    registry = build_registry()
    observed: dict[str, frozenset[RuleDomain]] = {}
    failures: list[str] = []

    for name, spec in sorted(registry.commands.items()):
        reachable = index.domains_for(spec.loader, spec.decide)
        observed[name] = reachable
        declared = frozenset(spec.rule_domains)
        if reachable != declared:
            missing = sorted(domain.value for domain in reachable - declared)
            stale = sorted(domain.value for domain in declared - reachable)
            failures.append(f"{name}: undeclared={missing}, unconsulted={stale}")

    assert observed.get("accept_offer"), "accept_offer found no domains; the walk is vacuous"
    assert observed.get("apply"), "apply found no domains; the walk is vacuous"
    assert not failures, "Command rule-domain contracts do not match:\n" + "\n".join(failures)
