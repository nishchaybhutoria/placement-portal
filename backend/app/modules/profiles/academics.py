"""Load PRO-1 academic-session context without bootstrapping application writes."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.domain.academics import (
    ACADEMIC_SESSION_SETTING,
    academic_session,
    academic_standing_status,
)


async def load_academic_session(
    executor: AsyncConnection | AsyncSession, *, lock: bool = False
) -> int | None:
    # A student save holds a shared lock until the executor commits, preventing
    # a concurrent session change from relabelling the submitted declaration.
    value = await executor.scalar(
        sa.text("SELECT value FROM settings WHERE key = :key" + (" FOR SHARE" if lock else "")),
        {"key": ACADEMIC_SESSION_SETTING},
    )
    return academic_session(value)


async def load_academic_standing(
    executor: AsyncConnection | AsyncSession, enrollment_id: UUID,
) -> dict[str, object]:
    row = (await executor.execute(
        sa.text("SELECT study_year, study_year_session FROM profiles WHERE enrollment_id = :id"),
        {"id": enrollment_id},
    )).mappings().one_or_none()
    return academic_standing_status(
        dict(row) if row is not None else {}, await load_academic_session(executor),
    )
