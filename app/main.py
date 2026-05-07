"""FastAPI app: Telegram webhook + healthcheck + lifespan tasks + cron endpoints.

Designed to run in two environments:

1. **Long-running server** (Railway/Docker) — full lifespan with background
   loops (`retry_pending_loop`, `daily_digest_loop`).
2. **Serverless** (Vercel) — `Settings.is_serverless` short-circuits the
   loops; instead, Vercel Cron hits `/api/cron/...` endpoints that perform
   one-shot work via the same business-logic functions.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from sqlalchemy import text
from telegram import Update

from app.background import (
    daily_digest_loop,
    daily_digest_once,
    retry_pending_loop,
    retry_pending_once,
)
from app.bot.application import build_application
from app.config import get_settings
from app.idempotency import already_handled
from app.logging import configure_logging, get_logger
from app.store.db import dispose_engine, get_engine

log = get_logger(__name__)

# Repo root: holds alembic.ini + migrations/ next to the `app/` package.
_REPO_ROOT = Path(__file__).resolve().parent.parent


def run_alembic_upgrade_head() -> str:
    """Run ``alembic upgrade head`` against the configured DATABASE_URL.

    Synchronous wrapper around Alembic's command API, intended to be called
    from the cron handler via ``asyncio.to_thread`` — Alembic's env.py uses
    ``asyncio.run`` internally, which fights any already-running event loop.
    Returns the head revision id (e.g. ``"0001"``) on success.
    """
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")
    head = ScriptDirectory.from_config(cfg).get_current_head()
    return head or ""


# Module-level cache for the Telegram Application. On a long-running server
# this is populated once during lifespan startup. On serverless platforms,
# the lifespan still runs once per cold start, so this is also amortized
# across warm invocations of the same container.
_tg_app = None


async def _get_or_init_tg_app():
    """Return the cached Telegram Application, initializing it on first call."""
    global _tg_app
    if _tg_app is not None:
        return _tg_app
    app_obj = build_application()
    await app_obj.initialize()
    await app_obj.start()
    _tg_app = app_obj
    return _tg_app


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    log.info(
        "startup",
        base_url=settings.base_url,
        model=settings.whisper_model,
        serverless=settings.is_serverless,
    )

    tg_app = await _get_or_init_tg_app()
    app.state.tg_app = tg_app

    tasks: list[asyncio.Task] = []
    if not settings.is_serverless:
        # Long-running server: run background loops in-process.
        tasks.append(asyncio.create_task(retry_pending_loop(), name="retry_pending"))

        async def _digest_send(text_msg: str) -> None:
            for uid in settings.allowed_user_ids:
                try:
                    await tg_app.bot.send_message(chat_id=uid, text=text_msg)
                except Exception as e:
                    log.warning("digest_send_failed", error=str(e), user_id=uid)

        tasks.append(asyncio.create_task(daily_digest_loop(_digest_send), name="daily_digest"))
    else:
        log.info("serverless_mode_skipping_background_loops")

    app.state.bg_tasks = tasks

    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError, Exception):
                await t
        # Lifespan runs once per worker, so we always tear down on exit.
        # On serverless this only fires when the container is being reclaimed.
        with suppress(Exception):
            await tg_app.stop()
            await tg_app.shutdown()
        if not settings.is_serverless:
            await dispose_engine()
        global _tg_app
        _tg_app = None
        log.info("shutdown")


app = FastAPI(lifespan=lifespan, title="biography-bot")


# ---------- public endpoints ----------


@app.get("/")
async def root() -> dict[str, str]:
    """Friendly root so a Vercel deployment URL doesn't 404 in the browser."""
    return {"service": "biography-bot", "status": "ok"}


@app.get("/healthz")
async def healthz() -> dict[str, object]:
    """Liveness/readiness probe. Verifies the DB is reachable."""
    settings = get_settings()
    db_ok = True
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        log.warning("healthz_db_failed", error=str(e))
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "db": db_ok,
        "bot_token_configured": bool(settings.telegram_bot_token),
        "model": settings.whisper_model,
        "serverless": settings.is_serverless,
    }


@app.post("/telegram/webhook/{secret}")
async def telegram_webhook(secret: str, request: Request) -> dict[str, str]:
    """Telegram webhook endpoint. Path includes a secret to prevent strangers POSTing."""
    settings = get_settings()
    if secret != settings.telegram_webhook_secret:
        raise HTTPException(status_code=403, detail="forbidden")

    payload = await request.json()
    update_id = payload.get("update_id")
    if isinstance(update_id, int) and already_handled(update_id):
        return {"status": "duplicate"}

    tg_app = getattr(request.app.state, "tg_app", None) or await _get_or_init_tg_app()
    update = Update.de_json(payload, tg_app.bot)
    await tg_app.process_update(update)
    return {"status": "ok"}


# ---------- cron (Vercel Cron Jobs) ----------


def _require_cron_auth(authorization: str | None) -> None:
    """Reject the request unless the caller presents the configured CRON_SECRET.

    Vercel Cron sends the `Authorization: Bearer <CRON_SECRET>` header
    automatically when `CRON_SECRET` is set as a project env var.
    """
    expected = get_settings().cron_secret
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_SECRET not configured")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=401, detail="invalid bearer token")


@app.get("/api/cron/retry-pending")
async def cron_retry_pending(
    authorization: str | None = Header(default=None),
) -> dict[str, int]:
    """Cron-friendly one-shot of the structuring retry job."""
    _require_cron_auth(authorization)
    return await retry_pending_once()


@app.get("/api/cron/daily-digest")
async def cron_daily_digest(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """Cron-friendly one-shot of the daily digest job."""
    _require_cron_auth(authorization)
    settings = get_settings()
    tg_app = await _get_or_init_tg_app()

    async def _send(text_msg: str) -> None:
        for uid in settings.allowed_user_ids:
            try:
                await tg_app.bot.send_message(chat_id=uid, text=text_msg)
            except Exception as e:
                log.warning("digest_send_failed", error=str(e), user_id=uid)

    return await daily_digest_once(_send)


@app.post("/api/cron/migrate")
async def cron_migrate(
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    """One-shot ``alembic upgrade head`` against the configured DATABASE_URL.

    Useful after pointing the project at a fresh Neon branch — instead of
    running migrations from a laptop, hit this endpoint with the cron bearer
    token and the schema is created in-place.
    """
    _require_cron_auth(authorization)
    log.info("cron_migrate_started")
    revision = await asyncio.to_thread(run_alembic_upgrade_head)
    log.info("cron_migrate_done", revision=revision)
    return {"status": "ok", "revision": revision}
