"""FastAPI smoke + webhook auth."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_healthz_returns_status(monkeypatch) -> None:
    # Patch out lifespan side effects so we don't hit Telegram or Postgres.
    from app import main

    fake_app = AsyncMock()
    fake_app.initialize = AsyncMock()
    fake_app.start = AsyncMock()
    fake_app.stop = AsyncMock()
    fake_app.shutdown = AsyncMock()
    fake_app.bot.send_message = AsyncMock()
    fake_app.process_update = AsyncMock()

    monkeypatch.setattr(main, "build_application", lambda: fake_app)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        async with main.lifespan(main.app):
            r = await client.get("/healthz")
            assert r.status_code == 200
            data = r.json()
            assert "status" in data
            assert data["model"]


@pytest.mark.asyncio
async def test_webhook_rejects_bad_secret(monkeypatch) -> None:
    from app import main

    fake_app = AsyncMock()
    fake_app.initialize = AsyncMock()
    fake_app.start = AsyncMock()
    fake_app.stop = AsyncMock()
    fake_app.shutdown = AsyncMock()
    fake_app.bot.send_message = AsyncMock()
    fake_app.process_update = AsyncMock()
    monkeypatch.setattr(main, "build_application", lambda: fake_app)

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        async with main.lifespan(main.app):
            r = await client.post("/telegram/webhook/wrong-secret", json={"update_id": 1})
            assert r.status_code == 403
