"""Run the M14 consistency command against a restored database."""

from __future__ import annotations

import asyncio
import json
import sys

from app.bootstrap import build_executor, build_registry
from app.core.db import create_engine
from app.core.plan import ActorContext
from app.modules.admin.commands import RunConsistencyCheckerInput


async def run() -> int:
    """Execute the real system command and return nonzero when drift is found."""
    engine = create_engine()
    executor = build_executor(build_registry(), engine)
    try:
        result = await executor.run(
            "run_consistency_checker",
            RunConsistencyCheckerInput(),
            ActorContext(principal_id="restore-drill", is_system=True),
        )
    finally:
        await engine.dispose()

    summary = result.summary
    sys.stdout.write(json.dumps(summary, sort_keys=True) + "\n")
    return 0 if summary.get("violations") == 0 else 2


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
