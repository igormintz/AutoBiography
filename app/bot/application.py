"""python-telegram-bot Application factory."""

from __future__ import annotations

from telegram import Update
from telegram.ext import Application, ApplicationBuilder

from app.bot.handlers import register
from app.config import get_settings


def build_application(*, polling: bool = False) -> Application:
    """Build a Telegram Application.

    polling=False (default): webhook mode — updater disabled, FastAPI handles updates.
    polling=True: local dev mode — built-in updater polls Telegram directly.
    """
    settings = get_settings()
    builder = ApplicationBuilder().token(settings.telegram_bot_token or "test-token")
    if not polling:
        # Disable the built-in updater; FastAPI forwards updates via process_update().
        builder = builder.updater(None)
    app = builder.build()
    register(app)
    return app


__all__ = ["Update", "build_application"]
