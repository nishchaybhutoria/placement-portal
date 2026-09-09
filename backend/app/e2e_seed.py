"""Seed the one shared database used by F5's serial browser suite."""

from __future__ import annotations

import asyncio

from app.seed import run_seed


def main() -> None:
    """Build the normal demo world plus the isolated E2E cohort once."""
    asyncio.run(run_seed(include_e2e=True))


if __name__ == "__main__":
    main()
