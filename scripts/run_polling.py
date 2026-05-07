"""Local dev runner: polling mode (no public URL needed).

Uses PTB's canonical ``Application.run_polling`` lifecycle. Background tasks
(``retry_pending_loop`` and ``daily_digest_loop``) are scheduled via
``post_init`` so they share the same event loop and are cancelled on shutdown.
"""

from __future__ import annotations

import asyncio

from telegram.ext import Application

from app.background import daily_digest_loop, retry_pending_loop
from app.bot.application import build_application
from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.store.db import dispose_engine

log = get_logger(__name__)

_background_tasks: list[asyncio.Task] = []


async def _post_init(app: Application) -> None:
    settings = get_settings()

    async def _digest_send(text: str) -> None:
        for uid in settings.allowed_user_ids:
            try:
                await app.bot.send_message(chat_id=uid, text=text)
            except Exception as e:
                log.warning("digest_send_failed", error=str(e), user_id=uid)

    _background_tasks.append(asyncio.create_task(retry_pending_loop(), name="retry_pending"))
    _background_tasks.append(
        asyncio.create_task(daily_digest_loop(_digest_send), name="daily_digest")
    )
    log.info("polling_ready", hint="Send a message to your bot now")


async def _post_shutdown(app: Application) -> None:
    for task in _background_tasks:
        task.cancel()
    await dispose_engine()
    log.info("shutdown")


def main() -> None:
    configure_logging()
    settings = get_settings()
    log.info("polling_start", model=settings.whisper_model)

    tg_app = build_application(polling=True)
    tg_app.post_init = _post_init
    tg_app.post_shutdown = _post_shutdown
    tg_app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
