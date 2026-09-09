"""M2 route limiter behavior from LLD section 11.1."""

import pytest

from app.core.errors import RateLimitExceeded
from app.core.rate_limit import InProcessRateLimiter


@pytest.mark.asyncio
async def test_rate_limit_is_isolated_per_principal() -> None:
    limiter = InProcessRateLimiter(clock=lambda: 100.0)

    await limiter.check("student-a", "bulk", "1/min")
    await limiter.check("student-b", "bulk", "1/min")

    with pytest.raises(RateLimitExceeded):
        await limiter.check("student-a", "bulk", "1/min")


@pytest.mark.asyncio
async def test_rate_limit_faults_fail_open() -> None:
    def broken_clock() -> float:
        raise OSError("clock unavailable")

    limiter = InProcessRateLimiter(clock=broken_clock)

    await limiter.check("student", "bulk", "10/min")
