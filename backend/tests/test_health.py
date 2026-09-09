"""M0 probe tests for LLD sections 14 and 15."""

from __future__ import annotations

import os

import httpx
import pytest

from app.main import create_app


async def _get(app_database_url: str, path: str) -> httpx.Response:
    application = create_app(app_database_url)
    async with application.router.lifespan_context(application):
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(path)


@pytest.mark.asyncio
async def test_healthz() -> None:
    response = await _get("postgresql+asyncpg://cds:cds@127.0.0.1:1/cds", "/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_readyz() -> None:
    database_url = os.environ["TEST_DATABASE_URL"]
    response = await _get(database_url, "/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_readyz_returns_503_when_database_is_unavailable() -> None:
    unavailable_url = "postgresql+asyncpg://cds:cds@127.0.0.1:1/cds"
    response = await _get(unavailable_url, "/readyz")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
