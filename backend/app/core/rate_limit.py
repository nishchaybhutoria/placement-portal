"""Small in-process route limiter for bulk and export commands."""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import Callable

from app.core.errors import RateLimitExceeded

LOGGER = logging.getLogger(__name__)


class InProcessRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._calls: defaultdict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def check(self, principal: str, command: str, rate: str | None) -> None:
        if rate is None:
            return
        try:
            count_text, interval = rate.split("/", maxsplit=1)
            if interval != "min":
                raise ValueError(f"Unsupported rate interval: {interval}")
            limit = int(count_text)
            now = self._clock()
            async with self._lock:
                calls = self._calls[(principal, command)]
                while calls and calls[0] <= now - 60:
                    calls.popleft()
                if len(calls) >= limit:
                    raise RateLimitExceeded
                calls.append(now)
        except RateLimitExceeded:
            raise
        except Exception:
            LOGGER.exception("Route limiter failed open", extra={"command": command})
