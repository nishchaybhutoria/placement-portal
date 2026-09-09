"""M5 domain modules remain database-free and traceable."""

import ast
from pathlib import Path

DOMAIN_ROOT = Path(__file__).parents[2] / "app" / "domain"


def test_M5_domain_modules_do_not_import_sqlalchemy_sessions_or_modules() -> None:
    forbidden: list[tuple[str, str]] = []
    for path in sorted(DOMAIN_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names.append(node.module)
            for name in names:
                if name == "sqlalchemy" or name.startswith(
                    ("sqlalchemy.", "app.core.db", "app.modules.")
                ):
                    forbidden.append((path.name, name))
    assert forbidden == []


def test_M5_every_owned_behavior_id_appears_in_a_test_name() -> None:
    names: set[str] = set()
    for path in sorted(Path(__file__).parent.glob("test_*.py")):
        tree = ast.parse(path.read_text())
        names.update(
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
    for behavior_id in (
        "ELG1",
        "ELG2",
        "ELG3",
        "DER1",
        "APP4",
        "OFR3",
        "OFR4",
        "OFR5",
        "RND3",
        "DIS",
        "CYC2",
    ):
        assert any(behavior_id in name for name in names), behavior_id
