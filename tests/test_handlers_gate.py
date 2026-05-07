"""Early allowlist gate handler short-circuits non-allowed updates."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram.ext import ApplicationHandlerStop

from app.bot import handlers, replies


@pytest.mark.asyncio
async def test_allowlist_gate_blocks_unknown_user_and_replies() -> None:
    update = MagicMock()
    update.effective_user.id = 999  # not in conftest allowlist (111, 222)
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    context = MagicMock()

    with pytest.raises(ApplicationHandlerStop):
        await handlers._allowlist_gate(update, context)

    update.message.reply_text.assert_awaited_once_with(replies.NOT_ALLOWED)


@pytest.mark.asyncio
async def test_allowlist_gate_blocks_user_with_no_user_id() -> None:
    update = MagicMock()
    update.effective_user = None
    update.message.reply_text = AsyncMock()
    update.callback_query = None
    context = MagicMock()

    with pytest.raises(ApplicationHandlerStop):
        await handlers._allowlist_gate(update, context)


@pytest.mark.asyncio
async def test_allowlist_gate_passes_listed_user() -> None:
    update = MagicMock()
    update.effective_user.id = 111  # in conftest allowlist
    update.message.reply_text = AsyncMock()
    context = MagicMock()

    # No exception means downstream handlers will run.
    await handlers._allowlist_gate(update, context)
    update.message.reply_text.assert_not_called()


@pytest.mark.asyncio
async def test_allowlist_gate_silent_when_no_message_to_reply_to() -> None:
    update = MagicMock()
    update.effective_user.id = 999
    update.message = None
    update.callback_query = None
    context = MagicMock()

    with pytest.raises(ApplicationHandlerStop):
        await handlers._allowlist_gate(update, context)
