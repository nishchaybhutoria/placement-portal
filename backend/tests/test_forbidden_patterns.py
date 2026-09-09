"""M0 proof tests for the forbidden-pattern CI gate in LLD section 14."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CHECKER = REPOSITORY_ROOT / "scripts" / "forbid.py"


def _run_checker(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CHECKER), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )


def _write_source(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


def test_forbidden_gate_rejects_planted_transaction_boundary(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "backend/app/modules/jobs/commands.py",
        "def mutate(tx):\n    tx.commit()\n",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "transaction boundary outside core/executor.py" in result.stderr


def test_forbidden_gate_rejects_planted_screen_session_access(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "backend/app/modules/jobs/screens.py",
        "def load(session):\n    return session.execute('SELECT 1')\n",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "direct session access in screen/router" in result.stderr


def test_forbidden_gate_allows_executor_and_alembic_transaction_boundaries(
    tmp_path: Path,
) -> None:
    _write_source(
        tmp_path,
        "backend/app/core/executor.py",
        "def execute(tx):\n    tx.begin()\n    tx.commit()\n",
    )
    _write_source(
        tmp_path,
        "backend/alembic/versions/0001_schema.py",
        "def upgrade(connection):\n    connection.begin()\n",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""


def test_forbidden_gate_rejects_planted_colour_literal_in_a_component(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "frontend/src/components/badge.tsx",
        'export const style = { color: "#bcc7de" };\n',
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "colour literal outside src/index.css" in result.stderr


def test_forbidden_gate_rejects_planted_functional_colour_literal(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "frontend/src/components/badge.css",
        ".badge { color: hsl(210 40% 50%); background: rgba(0, 0, 0, 0.5); }\n",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "colour literal outside src/index.css" in result.stderr


def test_forbidden_gate_allows_the_token_definition_file_and_token_references(
    tmp_path: Path,
) -> None:
    # index.css *defines* the palette; everything else only references it.
    _write_source(
        tmp_path,
        "frontend/src/index.css",
        ":root { --primary: 218.7 15.6% 39.0%; --ring: #545f73; }\n",
    )
    _write_source(
        tmp_path,
        "frontend/src/components/badge.tsx",
        'export const fill = "hsl(var(--primary) / <alpha-value>)";\n',
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""


def test_forbidden_gate_ignores_colours_named_in_comments(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "frontend/src/components/badge.tsx",
        "// The mockup used #bcc7de here; use the token instead.\n"
        "/* rgba(0, 0, 0, 0.5) was the old overlay. */\n"
        "export const fill = \"bg-primary\";\n",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""


def test_forbidden_gate_rejects_building_against_the_stitch_export(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "frontend/src/components/stolen.ts",
        'import tokens from "../../../docs/design/stitch/x/code.html";\n',
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 1
    assert "the Stitch export is reference-only" in result.stderr


def test_forbidden_gate_allows_citing_design_docs_in_prose(tmp_path: Path) -> None:
    _write_source(
        tmp_path,
        "frontend/src/lib/status.ts",
        "/** The data form of docs/design/DESIGN.md section 4. */\n"
        "export const STATUS = {};\n",
    )

    result = _run_checker(tmp_path)

    assert result.returncode == 0
    assert result.stderr == ""
