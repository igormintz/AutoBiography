"""Vercel / serverless-mode behaviour: config flag, lifespan, cron auth."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings


def test_is_serverless_false_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("SERVERLESS", raising=False)
    s = Settings()
    assert s.is_serverless is False


def test_is_serverless_true_when_vercel_env_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERCEL", "1")
    s = Settings()
    assert s.is_serverless is True


def test_is_serverless_true_when_serverless_flag_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.setenv("SERVERLESS", "true")
    s = Settings()
    assert s.is_serverless is True


@pytest.mark.asyncio
async def test_lifespan_skips_background_tasks_in_serverless(monkeypatch) -> None:
    """In serverless mode the lifespan must not start retry/digest loops."""
    import app.background as background
    from app import main

    fake_app = AsyncMock()
    fake_app.initialize = AsyncMock()
    fake_app.start = AsyncMock()
    fake_app.stop = AsyncMock()
    fake_app.shutdown = AsyncMock()
    fake_app.bot.send_message = AsyncMock()
    monkeypatch.setattr(main, "build_application", lambda: fake_app)

    called: dict[str, int] = {"retry": 0, "digest": 0}

    async def fake_retry() -> None:
        called["retry"] += 1

    async def fake_digest(_send) -> None:
        called["digest"] += 1

    monkeypatch.setattr(background, "retry_pending_loop", fake_retry)
    monkeypatch.setattr(background, "daily_digest_loop", fake_digest)
    monkeypatch.setattr(main, "retry_pending_loop", fake_retry)
    monkeypatch.setattr(main, "daily_digest_loop", fake_digest)

    monkeypatch.setenv("VERCEL", "1")
    main.get_settings.cache_clear()  # type: ignore[attr-defined]

    async with main.lifespan(main.app):
        pass

    assert called["retry"] == 0
    assert called["digest"] == 0

    monkeypatch.delenv("VERCEL", raising=False)
    main.get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cron_endpoint_rejects_unauthenticated(monkeypatch) -> None:
    from app import main

    fake_app = AsyncMock()
    fake_app.initialize = AsyncMock()
    fake_app.start = AsyncMock()
    fake_app.stop = AsyncMock()
    fake_app.shutdown = AsyncMock()
    fake_app.bot.send_message = AsyncMock()
    monkeypatch.setattr(main, "build_application", lambda: fake_app)

    monkeypatch.setenv("CRON_SECRET", "expected-secret")
    main.get_settings.cache_clear()  # type: ignore[attr-defined]

    transport = ASGITransport(app=main.app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        main.lifespan(main.app),
    ):
        r = await client.get("/api/cron/retry-pending")
        assert r.status_code == 401

        r = await client.get(
            "/api/cron/retry-pending",
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401

    monkeypatch.delenv("CRON_SECRET", raising=False)
    main.get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cron_endpoint_accepts_correct_bearer(monkeypatch) -> None:
    from app import main

    fake_app = AsyncMock()
    fake_app.initialize = AsyncMock()
    fake_app.start = AsyncMock()
    fake_app.stop = AsyncMock()
    fake_app.shutdown = AsyncMock()
    fake_app.bot.send_message = AsyncMock()
    monkeypatch.setattr(main, "build_application", lambda: fake_app)

    async def fake_retry_once() -> dict:
        return {"processed": 0, "succeeded": 0}

    monkeypatch.setattr(main, "retry_pending_once", fake_retry_once)
    monkeypatch.setenv("CRON_SECRET", "expected-secret")
    main.get_settings.cache_clear()  # type: ignore[attr-defined]

    transport = ASGITransport(app=main.app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        main.lifespan(main.app),
    ):
        r = await client.get(
            "/api/cron/retry-pending",
            headers={"Authorization": "Bearer expected-secret"},
        )
        assert r.status_code == 200
        assert r.json()["processed"] == 0

    monkeypatch.delenv("CRON_SECRET", raising=False)
    main.get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cron_migrate_rejects_unauthenticated(monkeypatch) -> None:
    from app import main

    fake_app = AsyncMock()
    fake_app.initialize = AsyncMock()
    fake_app.start = AsyncMock()
    fake_app.stop = AsyncMock()
    fake_app.shutdown = AsyncMock()
    fake_app.bot.send_message = AsyncMock()
    monkeypatch.setattr(main, "build_application", lambda: fake_app)

    monkeypatch.setenv("CRON_SECRET", "expected-secret")
    main.get_settings.cache_clear()  # type: ignore[attr-defined]

    transport = ASGITransport(app=main.app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        main.lifespan(main.app),
    ):
        r = await client.post("/api/cron/migrate")
        assert r.status_code == 401

        r = await client.post(
            "/api/cron/migrate",
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401

    monkeypatch.delenv("CRON_SECRET", raising=False)
    main.get_settings.cache_clear()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_cron_migrate_runs_upgrade_head_when_authorized(monkeypatch) -> None:
    from app import main

    fake_app = AsyncMock()
    fake_app.initialize = AsyncMock()
    fake_app.start = AsyncMock()
    fake_app.stop = AsyncMock()
    fake_app.shutdown = AsyncMock()
    fake_app.bot.send_message = AsyncMock()
    monkeypatch.setattr(main, "build_application", lambda: fake_app)

    called = {"count": 0}

    def fake_upgrade_head() -> str:
        called["count"] += 1
        return "0001"

    monkeypatch.setattr(main, "run_alembic_upgrade_head", fake_upgrade_head)
    monkeypatch.setenv("CRON_SECRET", "expected-secret")
    main.get_settings.cache_clear()  # type: ignore[attr-defined]

    transport = ASGITransport(app=main.app)
    async with (
        AsyncClient(transport=transport, base_url="http://test") as client,
        main.lifespan(main.app),
    ):
        r = await client.post(
            "/api/cron/migrate",
            headers={"Authorization": "Bearer expected-secret"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["revision"] == "0001"

    assert called["count"] == 1

    monkeypatch.delenv("CRON_SECRET", raising=False)
    main.get_settings.cache_clear()  # type: ignore[attr-defined]
