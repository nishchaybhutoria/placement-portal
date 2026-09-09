"""Database-session contract tests."""

import pytest

from app.core.db import sessionmaker


@pytest.mark.asyncio
async def test_sessionmaker_disables_implicit_transactions_and_expiration() -> None:
    async with sessionmaker() as session:
        assert session.sync_session.autobegin is False
        assert session.sync_session.expire_on_commit is False
