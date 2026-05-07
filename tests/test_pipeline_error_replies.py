"""Voice/text pipeline failures must surface the real error to Telegram.

Earlier the handlers replied with the misleading constant "שגיאה בתמלול…"
even when the failure was downstream (DB, structuring, Drive). Now they use
``replies.error_message(error=..., update_id=...)`` so the user sees the
exception class, a short message, and the Telegram update_id for grepping.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.bot import handlers


@pytest.mark.asyncio
async def test_run_voice_pipeline_surfaces_real_error(monkeypatch) -> None:
    from app.pipeline import orchestrator

    async def boom(*args, **kwargs):
        raise ValueError("relation entries does not exist")

    monkeypatch.setattr(orchestrator, "process_voice", boom)

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    await handlers._run_voice_pipeline(
        audio_bytes=b"fake-audio",
        chat_id=10,
        ack_message_id=20,
        bot=bot,
        update_id=4242,
    )

    bot.send_message.assert_awaited_once()
    sent = bot.send_message.await_args.kwargs["text"]
    assert "ValueError" in sent
    assert "relation entries does not exist" in sent
    assert "4242" in sent


@pytest.mark.asyncio
async def test_run_text_pipeline_surfaces_real_error(monkeypatch) -> None:
    from app.pipeline import orchestrator

    async def boom(*args, **kwargs):
        raise RuntimeError("downstream kapow")

    monkeypatch.setattr(orchestrator, "process_text", boom)

    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.edit_message_text = AsyncMock()

    await handlers._run_text_pipeline(
        text="hi",
        chat_id=11,
        ack_message_id=22,
        bot=bot,
        update_id=7777,
    )

    bot.send_message.assert_awaited_once()
    sent = bot.send_message.await_args.kwargs["text"]
    assert "RuntimeError" in sent
    assert "downstream kapow" in sent
    assert "7777" in sent
