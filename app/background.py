"""Background tasks: retry needs_structuring, send daily digest.

Two execution shapes:

* **Long-lived loops** (`retry_pending_loop`, `daily_digest_loop`) — used by
  the FastAPI lifespan when running on a long-running server (Railway/Docker).
* **One-shot callables** (`retry_pending_once`, `daily_digest_once`) — used
  by serverless cron endpoints (Vercel Cron) where each invocation must be
  short-lived and idempotent.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.logging import get_logger
from app.obs.usage import daily_digest_text
from app.pipeline.structure import structure_with_retry
from app.store import repo
from app.store.db import session_scope

log = get_logger(__name__)


async def retry_pending_once(*, limit: int = 10) -> dict[str, int]:
    """Run a single pass of the retry-pending logic.

    Returns a small summary dict so callers (cron endpoints) can return it
    as JSON for observability.
    """
    processed = 0
    succeeded = 0
    try:
        async with session_scope() as session:
            pending = await repo.list_pending_structuring(session, limit=limit)
        for entry in pending:
            processed += 1
            result = await structure_with_retry(entry.transcript, max_attempts=2)
            if result is None:
                continue
            async with session_scope() as session:
                fresh = await repo.get_by_short_id(session, entry.short_id)
                if fresh is None:
                    continue
                await repo.update_entry(
                    session,
                    fresh,
                    summary=result.data.summary,
                    tags=list(result.data.tags),
                    entities=list(result.data.entities),
                    approx_age=result.data.timeline.approx_age,
                    year=result.data.timeline.year,
                    follow_up_questions=list(result.data.follow_up_questions),
                    status="ok",
                )
                await repo.record_usage(
                    session,
                    kind="structure",
                    cost_usd=result.cost_usd,
                    tokens_in=result.tokens_in,
                    tokens_out=result.tokens_out,
                    entry_id=fresh.id,
                )
            succeeded += 1
            log.info("retry_structuring_succeeded", short_id=entry.short_id)
    except Exception as e:
        log.exception("retry_pending_once_error", error=str(e))
    return {"processed": processed, "succeeded": succeeded}


async def retry_pending_loop(interval_seconds: int = 1800) -> None:
    """Every interval_seconds, retry structuring on entries flagged needs_structuring."""
    while True:
        await retry_pending_once()
        await asyncio.sleep(interval_seconds)


SendCallback = Callable[[str], Awaitable[None]]


async def daily_digest_once(send_callback: SendCallback) -> dict[str, str]:
    """Compute and send the digest exactly once. Safe to call from a cron."""
    text = await daily_digest_text()
    await send_callback(text)
    return {"sent": "ok", "chars": str(len(text))}


async def daily_digest_loop(send_callback: SendCallback) -> None:
    """Wake up every 60s, send the digest once at 09:00 in the configured timezone."""
    tz = ZoneInfo(get_settings().timezone)
    last_sent_date: str | None = None
    target = time(hour=9, minute=0)

    while True:
        try:
            now_local = datetime.now(tz)
            today_str = now_local.date().isoformat()
            if now_local.time() >= target and last_sent_date != today_str:
                await daily_digest_once(send_callback)
                last_sent_date = today_str
        except Exception as e:
            log.exception("daily_digest_loop_error", error=str(e))
        await asyncio.sleep(60)


def next_daily_run(now: datetime, target: time, tz: ZoneInfo) -> datetime:
    """Helper used by tests: next datetime when the digest should fire."""
    local_now = now.astimezone(tz)
    candidate = local_now.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate
