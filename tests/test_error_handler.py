"""Global PTB error handler: logging + user-facing reply."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import ApplicationBuilder

from app.bot import handlers
from app.bot.handlers import handle_error


def test_register_attaches_error_handler() -> None:
    app = ApplicationBuilder().token("1:test").build()
    handlers.register(app)
    assert handle_error in app.error_handlers


@pytest.mark.asyncio
async def test_handle_error_replies_with_generic_message() -> None:
    update = MagicMock()
    update.update_id = 4242
    update.effective_chat = MagicMock(id=10)
    update.effective_user = MagicMock(id=20)
    update.message = MagicMock()
    update.message.reply_text = AsyncMock()

    context = MagicMock()
    context.error = ValueError("boom")
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()

    await handle_error(update, context)

    sent_via_reply = update.message.reply_text.await_count == 1
    sent_via_bot = context.bot.send_message.await_count == 1
    assert sent_via_reply or sent_via_bot


@pytest.mark.asyncio
async def test_handle_error_no_message_does_not_crash() -> None:
    update = MagicMock()
    update.update_id = 1
    update.effective_chat = None
    update.effective_user = None
    update.message = None

    context = MagicMock()
    context.error = RuntimeError("bad")
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock()

    await handle_error(update, context)
    assert context.bot.send_message.await_count == 0


@pytest.mark.asyncio
async def test_handle_error_swallows_reply_failure() -> None:
    update = MagicMock()
    update.update_id = 5
    update.effective_chat = MagicMock(id=99)
    update.effective_user = MagicMock(id=99)
    update.message = MagicMock()
    update.message.reply_text = AsyncMock(side_effect=Exception("network down"))

    context = MagicMock()
    context.error = ValueError("boom")
    context.bot = MagicMock()
    context.bot.send_message = AsyncMock(side_effect=Exception("also down"))

    await handle_error(update, context)
