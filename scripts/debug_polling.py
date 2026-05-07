"""Diagnostic polling runner.

Logs every incoming update to stdout via an error handler + catch-all message handler
in group=-1, then runs the main `register(app)` handlers in the default group.
Use to confirm whether updates are dispatching correctly.
"""

from __future__ import annotations

import logging
import sys

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.bot.handlers import register
from app.config import get_settings


async def _log_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.message
    print(
        f"[debug_dispatch] update_id={update.update_id} "
        f"from={msg.from_user.id if msg and msg.from_user else None} "
        f"chat={msg.chat.id if msg and msg.chat else None} "
        f"voice={bool(msg and msg.voice)} text={msg.text if msg else None!r}",
        flush=True,
    )


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"[debug_error] {context.error!r}", flush=True)
    import traceback

    traceback.print_exception(type(context.error), context.error, context.error.__traceback__)
    sys.stdout.flush()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stdout,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("telegram.ext").setLevel(logging.DEBUG)
    settings = get_settings()
    app: Application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.add_handler(MessageHandler(filters.ALL, _log_update), group=-1)
    register(app)
    app.add_error_handler(_on_error)
    print("[debug_dispatch] starting run_polling", flush=True)
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
