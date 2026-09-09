#!/usr/bin/env python3
"""Reject write-path patterns forbidden by CONTRIBUTING.md and LLD section 14."""

from __future__ import annotations

import argparse
import logging
import re
from collections.abc import Iterable
from pathlib import Path

TRANSACTION_PATTERN = re.compile(r"\.(?:commit|begin)\s*\(")
SCREEN_SESSION_PATTERN = re.compile(r"\bsession\s*\.")

# Colour literals in frontend sources. Every colour must come from a design
# token, so that light and dark stay in step and DESIGN.md stays the only place
# a palette is decided. Matches #rgb/#rrggbb/#rrggbbaa, and rgb()/hsl() with
# their a-variants and the modern slash-alpha form.
HEX_COLOUR_PATTERN = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
FUNCTIONAL_COLOUR_PATTERN = re.compile(r"\b(?:rgba?|hsla?)\s*\(")
# `hsl(var(--token) / <alpha-value>)` is how a token is *referenced*, not a
# literal; tailwind.config.ts is built out of exactly this form.
TOKEN_REFERENCE_PATTERN = re.compile(r"\b(?:rgba?|hsla?)\s*\(\s*var\(\s*--")

FRONTEND_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".css", ".html"}
# The single file allowed to hold literals: it *defines* the tokens.
COLOUR_LITERAL_ALLOWLIST = {("frontend", "src", "index.css")}
# Generated output is not hand-written source; it is regenerated, not edited.
COLOUR_LITERAL_SKIP_PREFIXES = {("frontend", "src", "api", "gen")}

# The Stitch export is reference-only (docs/design/README.md): nothing under
# frontend/ may import from it, alias it, or load an asset out of it. Prose that
# *cites* DESIGN.md is fine and lives in comments, which are stripped first.
DESIGN_REFERENCE_PATTERN = re.compile(
    r"""(?:\bfrom\s*|\bimport\s*\(|\brequire\s*\(|@import\s*|\b(?:src|href)\s*=\s*)"""
    r"""["'`][^"'`]*docs/design"""
)

_BLOCK_COMMENTS = {
    ".ts": ("/*", "*/"),
    ".tsx": ("/*", "*/"),
    ".js": ("/*", "*/"),
    ".jsx": ("/*", "*/"),
    ".css": ("/*", "*/"),
    ".html": ("<!--", "-->"),
}
_LINE_COMMENT_SUFFIXES = {".ts", ".tsx", ".js", ".jsx"}
# `//` only starts a comment when it is not the `://` of a URL.
LINE_COMMENT_PATTERN = re.compile(r"(?<!:)//")

LOGGER = logging.getLogger("forbidden-patterns")


def _python_sources(root: Path) -> Iterable[Path]:
    candidates = [root / "backend", root / "scripts"]
    ignored_parts = {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
    for source_root in candidates:
        if not source_root.is_dir():
            continue
        for path in sorted(source_root.rglob("*.py")):
            relative = path.relative_to(root)
            if ignored_parts.intersection(relative.parts):
                continue
            if relative.parts[:2] == ("backend", "tests"):
                continue
            yield path


def _is_executor(path: Path, root: Path) -> bool:
    return path == root / "backend" / "app" / "core" / "executor.py"


def _is_alembic(path: Path, root: Path) -> bool:
    relative = path.relative_to(root)
    return relative.parts[:2] == ("backend", "alembic")


def _frontend_sources(root: Path) -> Iterable[Path]:
    source_root = root / "frontend" / "src"
    if not source_root.is_dir():
        return
    ignored_parts = {"node_modules", "dist", ".vite"}
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix not in FRONTEND_SOURCE_SUFFIXES:
            continue
        relative = path.relative_to(root)
        if ignored_parts.intersection(relative.parts):
            continue
        yield path


def _frontend_config_sources(root: Path) -> Iterable[Path]:
    """Top-level frontend files that may reference docs/design but not colours."""
    frontend = root / "frontend"
    if not frontend.is_dir():
        return
    for name in ("tailwind.config.ts", "vite.config.ts", "postcss.config.js", "index.html"):
        path = frontend / name
        if path.is_file():
            yield path


def _colour_literals_allowed(relative: Path) -> bool:
    parts = relative.parts
    if parts in COLOUR_LITERAL_ALLOWLIST:
        return True
    return any(parts[: len(prefix)] == prefix for prefix in COLOUR_LITERAL_SKIP_PREFIXES)


def _strip_token_references(line: str) -> str:
    """Blank out `hsl(var(--x) / …)` so only real literals remain."""
    return TOKEN_REFERENCE_PATTERN.sub("", line)


def _strip_comments(text: str, suffix: str) -> list[str]:
    """Blank out comments, preserving line count so line numbers stay true.

    Comments are where DESIGN.md gets cited and where example colours get
    written down; the gate is about code, so they must not trip it.
    """
    open_token, close_token = _BLOCK_COMMENTS.get(suffix, ("/*", "*/"))
    lines: list[str] = []
    in_block = False
    for line in text.splitlines():
        result: list[str] = []
        index = 0
        while index < len(line):
            if in_block:
                end = line.find(close_token, index)
                if end == -1:
                    index = len(line)
                    break
                in_block = False
                index = end + len(close_token)
                continue
            start = line.find(open_token, index)
            comment = LINE_COMMENT_PATTERN.search(line, index) if suffix in _LINE_COMMENT_SUFFIXES else None
            if comment is not None and (start == -1 or comment.start() < start):
                result.append(line[index : comment.start()])
                index = len(line)
                break
            if start == -1:
                result.append(line[index:])
                break
            result.append(line[index:start])
            in_block = True
            index = start + len(open_token)
        lines.append("".join(result))
    return lines


def _is_screen_or_router(path: Path) -> bool:
    name = path.name
    return (
        name == "screens.py"
        or name in {"router.py", "routers.py"}
        or name.endswith("_router.py")
        or "routers" in path.parts
    )


def find_violations(root: Path) -> list[str]:
    """Return stable, line-addressed violations below ``root``."""
    violations: list[str] = []
    for path in _python_sources(root):
        relative = path.relative_to(root)
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            transaction_boundary_allowed = _is_executor(path, root) or _is_alembic(path, root)
            if not transaction_boundary_allowed and TRANSACTION_PATTERN.search(line):
                violations.append(
                    f"{relative}:{line_number}: transaction boundary outside core/executor.py"
                )
            if _is_screen_or_router(relative) and SCREEN_SESSION_PATTERN.search(line):
                violations.append(
                    f"{relative}:{line_number}: direct session access in screen/router"
                )

    for path in (*_frontend_sources(root), *_frontend_config_sources(root)):
        relative = path.relative_to(root)
        allowed = _colour_literals_allowed(relative)
        source = _strip_comments(path.read_text(encoding="utf-8"), path.suffix)
        for line_number, line in enumerate(source, 1):
            if not allowed:
                stripped = _strip_token_references(line)
                if HEX_COLOUR_PATTERN.search(stripped) or FUNCTIONAL_COLOUR_PATTERN.search(
                    stripped
                ):
                    violations.append(
                        f"{relative}:{line_number}: colour literal outside src/index.css"
                        " — use a design token"
                    )
            if DESIGN_REFERENCE_PATTERN.search(line):
                violations.append(
                    f"{relative}:{line_number}: reference to docs/design"
                    " — the Stitch export is reference-only"
                )
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    violations = find_violations(args.root.resolve())
    if not violations:
        return 0

    logging.basicConfig(level=logging.ERROR, format="%(message)s")
    LOGGER.error("Forbidden source patterns found:")
    for violation in violations:
        LOGGER.error("- %s", violation)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
