"""The ratchet: analytics may not name an offer table.

Every other test in this milestone compares analytics against
`modules/offers/derivations.py` on a fixture.  None of them would notice a
future session rewriting `metrics.py` into hand-tuned SQL that happens to agree
with the fixture: the equivalence suites would go on passing, green and
meaningless, until a case the fixture does not contain -- a termination, an
unattached external, a second acceptance -- diverged in production and put two
different numbers on two screens.

So the guarantee is structural rather than behavioural.  ``modules/analytics``
does not get to have an opinion about what "accepted" means, because it is not
allowed to write the query: the only way it can reach an offer row is through a
fragment defined in ``derivations.py``, next to the one the ELG-3 gates use.

``test_the_ratchet_bites`` plants the violation this module exists to catch, so
the guard cannot quietly stop working.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ANALYTICS = Path(__file__).resolve().parents[2] / "app" / "modules" / "analytics"
DERIVATIONS = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "modules"
    / "offers"
    / "derivations.py"
)

#: The two tables whose interpretation is DER-1's and nobody else's.  Matched
#: as SQL identifiers -- after FROM/JOIN/INTO/UPDATE, or qualifying a column --
#: so prose in a docstring naming the tables is not a violation while
#: ``FROM offers`` is.
FORBIDDEN_TABLES = ("offers", "external_offers")

_TABLE_REFERENCE = re.compile(
    r"\b(?:from|join|into|update)\s+(?:public\.)?(offers|external_offers)\b",
    re.IGNORECASE,
)


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """The Constant nodes that are docstrings, by identity.

    A docstring is a string constant like any other, so scanning literals
    naively flags the sentence "must not select from offers" as if it were the
    query it forbids.  SQL is never a docstring, and prose about the rule
    belongs in one, so docstrings are the one kind of literal exempt here.
    Comments never reach the AST at all and are exempt for free.
    """
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ):
            continue
        body = getattr(node, "body", [])
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
            if isinstance(first.value.value, str):
                found.add(id(first.value))
    return found


def _string_literals(source: str) -> list[tuple[int, str]]:
    """Every non-docstring string constant, with the line it starts on."""
    tree = ast.parse(source)
    exempt = _docstring_nodes(tree)
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in exempt:
                continue
            found.append((node.lineno, node.value))
    return found


def _violations(source: str) -> list[str]:
    problems: list[str] = []
    for lineno, literal in _string_literals(source):
        for match in _TABLE_REFERENCE.finditer(literal):
            problems.append(f"line {lineno}: SQL names `{match.group(1)}`")
    return problems


def _analytics_sources() -> list[Path]:
    return sorted(
        path
        for path in ANALYTICS.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def test_analytics_never_writes_its_own_offer_sql() -> None:
    """No module under analytics may select from an offer table."""
    offenders: dict[str, list[str]] = {}
    for path in _analytics_sources():
        problems = _violations(path.read_text(encoding="utf-8"))
        if problems:
            offenders[path.name] = problems
    assert not offenders, (
        "modules/analytics must reach offer rows only through the fragments in "
        "modules/offers/derivations.py, so the dashboards and the ELG-3 gates "
        "cannot grow two definitions of 'accepted'. Import the fragment (or add "
        "one there) instead of writing the query here.\n"
        + "\n".join(
            f"  {name}: {'; '.join(problems)}" for name, problems in offenders.items()
        )
    )


def test_the_ratchet_bites() -> None:
    """Plant the violation, prove the guard catches it.

    A guard nobody has ever seen fail is a guard nobody knows is wired up.
    """
    planted = (
        "QUERY = '''\n"
        "    SELECT enrollment_id FROM offers WHERE response = 'accepted'\n"
        "'''\n"
    )
    assert _violations(planted) == ["line 1: SQL names `offers`"]

    also_planted = "SQL = 'SELECT 1 FROM external_offers eo'"
    assert _violations(also_planted) == ["line 1: SQL names `external_offers`"]

    # Prose about the rule is not the rule being broken.  A docstring saying
    # "must not select from offers" is exempt; the same words in an assigned
    # constant are not, because that is where a query would actually live.
    innocent = '"""Analytics must not select from offers directly."""'
    assert _violations(innocent) == []
    assert _violations('X = "SELECT 1 FROM offers"') == ["line 1: SQL names `offers`"]


def test_analytics_actually_imports_the_derivation_fragments() -> None:
    """The other half: forbidding the query is useless if nothing uses the one.

    A metrics module that named no offer table *and* imported no fragment would
    pass the guard above by computing nothing at all.
    """
    metrics = (ANALYTICS / "metrics.py").read_text(encoding="utf-8")
    for fragment in (
        "ACCEPTED_PORTAL_OFFERS_SQL",
        "ACCEPTED_EXTERNAL_OFFERS_SQL",
        "EXTENDED_PORTAL_OFFERS_SQL",
        "OFFERED_EXTERNAL_OFFERS_SQL",
    ):
        assert fragment in metrics, (
            f"metrics.py no longer builds on {fragment}; ANA-1 counts what "
            "DER-1 defines, so every offer fact comes from one of these."
        )
        assert fragment in DERIVATIONS.read_text(encoding="utf-8"), (
            f"{fragment} has left derivations.py -- the fragments and the gates "
            "must stay in the same file, which is the whole point."
        )
