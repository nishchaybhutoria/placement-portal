"""Fail when a checked-in Markdown link points to a missing local file."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def markdown_files() -> list[Path]:
    roots = [
        *ROOT.glob("*.md"),
        *ROOT.glob("docs/**/*.md"),
        *ROOT.glob(".github/**/*.md"),
    ]
    return sorted(path for path in roots if ".git" not in path.parts)


def missing_links(path: Path) -> list[str]:
    failures: list[str] = []
    source = path.read_text(encoding="utf-8")
    for raw in LINK.findall(source):
        target = raw.strip().split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith(("#", "http://", "https://", "mailto:")):
            continue
        relative = unquote(target.split("#", 1)[0])
        if relative and not (path.parent / relative).resolve().exists():
            failures.append(target)
    return failures


def main() -> int:
    failures = [
        f"{path.relative_to(ROOT)}: {target}"
        for path in markdown_files()
        for target in missing_links(path)
    ]
    if failures:
        print("Broken local Markdown links:", file=sys.stderr)
        print("\n".join(f"  {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(f"Documentation links passed ({len(markdown_files())} Markdown files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
