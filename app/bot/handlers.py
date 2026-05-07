"""Telegram message + command handlers."""

from __future__ import annotations

import time
from datetime import datetime, timezone

import structlog
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    TypeHandler,
    filters,
)

from app.auth import is_allowed
from app.bot import replies, state
from app.logging import get_logger
from app.pipeline import orchestrator
from app.pipeline.structure import structure_with_retry
from app.store import repo
from app.store.db import session_scope
from app.store.local_store import LocalStore

log = get_logger(__name__)

# Local store is built lazily; tests override via _override_drive_for_tests.
_drive: LocalStore | None = None


def _drive_or_none() -> LocalStore | None:
    global _drive
    if _drive is not None:
        return _drive
    try:
        _drive = LocalStore.from_settings()
    except Exception as e:
        log.warning("local_store_unavailable", error=str(e))
        _drive = None
    return _drive


def _override_drive_for_tests(drive: LocalStore | None) -> None:
    global _drive
    _drive = drive


# ----- guards -----


def _require_user(update: Update) -> int | None:
    user = update.effective_user
    if not user or not is_allowed(user.id):
        return None
    return user.id


async def _refuse(update: Update) -> None:
    if update.message:
        await update.message.reply_text(replies.NOT_ALLOWED)


async def _allowlist_gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Pre-handler that short-circuits any update from a non-allowlisted user.

    Registered at ``group=-1`` so it runs before every other handler. Raising
    ``ApplicationHandlerStop`` prevents PTB from dispatching the update to any
    later group (no audio download, no DB lookup, no LLM call).
    """
    user = update.effective_user
    user_id = user.id if user else None
    if user_id is not None and is_allowed(user_id):
        return

    log.info(
        "update_refused",
        reason="not_allowed",
        user_id=user_id,
        update_id=getattr(update, "update_id", None),
    )
    msg = update.message or (
        update.callback_query.message if update.callback_query is not None else None
    )
    if msg is not None:
        try:
            await msg.reply_text(replies.NOT_ALLOWED)
        except Exception as e:
            log.debug("refusal_reply_failed", error=str(e))
    raise ApplicationHandlerStop


# ----- handlers -----


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    await update.message.reply_text(replies.START)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    await update.message.reply_text(replies.HELP)


async def cmd_last(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    async with session_scope() as session:
        entry = await repo.get_last(session)
    if entry is None:
        await update.message.reply_text("עדיין אין רישומים.")
        return
    await update.message.reply_text(replies.format_compact(entry))


async def cmd_show(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    if not context.args:
        await update.message.reply_text("שימוש: /show <id>")
        return
    short_id = context.args[0].upper()
    async with session_scope() as session:
        entry = await repo.get_by_short_id(session, short_id)
    if entry is None:
        await update.message.reply_text(replies.NOT_FOUND)
        return
    await update.message.reply_text(replies.format_full_bundle(entry))


async def cmd_questions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    async with session_scope() as session:
        entry = await repo.get_last(session)
    if entry is None:
        await update.message.reply_text("עדיין אין רישומים.")
        return
    await update.message.reply_text(replies.format_questions(entry))


async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    if not context.args:
        await update.message.reply_text("שימוש: /edit <id>")
        return
    short_id = context.args[0].upper()
    async with session_scope() as session:
        entry = await repo.get_by_short_id(session, short_id)
    if entry is None:
        await update.message.reply_text(replies.NOT_FOUND)
        return
    state.set_pending(
        update.effective_chat.id,
        state.PendingAction(kind="edit", short_id=short_id),
    )
    await update.message.reply_text(
        f"התמליל הנוכחי לרישום {short_id}:\n\n{entry.transcript}\n\n{replies.EDIT_PROMPT}"
    )


async def cmd_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    if not context.args:
        await update.message.reply_text("שימוש: /tags <id>")
        return
    short_id = context.args[0].upper()
    async with session_scope() as session:
        entry = await repo.get_by_short_id(session, short_id)
    if entry is None:
        await update.message.reply_text(replies.NOT_FOUND)
        return
    state.set_pending(
        update.effective_chat.id,
        state.PendingAction(kind="tags", short_id=short_id),
    )
    await update.message.reply_text(replies.format_tags(entry))


async def cmd_restructure(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    if not context.args:
        await update.message.reply_text("שימוש: /restructure <id>")
        return
    short_id = context.args[0].upper()
    async with session_scope() as session:
        entry = await repo.get_by_short_id(session, short_id)
    if entry is None:
        await update.message.reply_text(replies.NOT_FOUND)
        return

    result = await structure_with_retry(entry.transcript)
    if result is None:
        async with session_scope() as session:
            fresh = await repo.get_by_short_id(session, short_id)
            if fresh is not None:
                await repo.update_entry(session, fresh, status="needs_structuring")
        await update.message.reply_text(replies.NEEDS_STRUCTURING)
        return

    async with session_scope() as session:
        fresh = await repo.get_by_short_id(session, short_id)
        if fresh is None:
            await update.message.reply_text(replies.NOT_FOUND)
            return
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
        refreshed = fresh

    await update.message.reply_text(replies.format_full_bundle(refreshed))


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    if not context.args:
        await update.message.reply_text("שימוש: /search <text>")
        return
    term = " ".join(context.args)
    async with session_scope() as session:
        results = await repo.search_transcript(session, term, limit=5)
    await update.message.reply_text(replies.format_search_results(results))


async def cmd_usage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _require_user(update) is None:
        await _refuse(update)
        return
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    async with session_scope() as session:
        totals = await repo.usage_since(session, today)
    msg = (
        "📊 שימוש היום\n"
        f"• אירועים: {totals['events']}\n"
        f"• שניות תמלול: {totals['transcribe_seconds']}\n"
        f"• טוקנים LLM: {totals['tokens_in']} ↓ / {totals['tokens_out']} ↑\n"
        f"• עלות מוערכת: ${totals['cost_usd']:.4f}"
    )
    await update.message.reply_text(msg)


# ----- voice / text dispatch -----


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _bind_request_context(update)
    if _require_user(update) is None:
        log.info("voice_refused", reason="not_allowed")
        await _refuse(update)
        return
    if not update.message or not (update.message.voice or update.message.audio):
        return

    media = update.message.voice or update.message.audio
    duration = float(getattr(media, "duration", 0) or 0)
    file_size = int(getattr(media, "file_size", 0) or 0)
    log.info(
        "voice_received",
        duration_seconds=duration,
        file_size_bytes=file_size,
        mime_type=getattr(media, "mime_type", None),
    )

    ack = await update.message.reply_text(
        replies.status_received(audio_seconds=duration, file_size_bytes=file_size)
    )

    download_started = time.perf_counter()
    file = await context.bot.get_file(media.file_id)
    audio_bytes = bytes(await file.download_as_bytearray())
    log.info(
        "voice_downloaded",
        bytes=len(audio_bytes),
        seconds=time.perf_counter() - download_started,
    )

    # Run the pipeline inline. Detaching it as a background task only works on
    # long-lived processes (Railway/Docker); on serverless platforms the
    # function is frozen the moment the webhook responds, killing background
    # work mid-flight. Awaiting inline holds the webhook open until the
    # pipeline completes (well within Vercel's `maxDuration`), and is safe on
    # long-lived servers too — concurrent updates still execute in parallel
    # via FastAPI/PTB's per-update tasks.
    await _run_voice_pipeline(
        audio_bytes=audio_bytes,
        chat_id=update.effective_chat.id,
        ack_message_id=ack.message_id,
        bot=context.bot,
        update_id=getattr(update, "update_id", None),
    )


def _make_status_editor(bot, chat_id: int, message_id: int):
    """Build a status callback that edits the ack message in place."""
    last_text: dict[str, str] = {"value": ""}

    async def _emit(text: str) -> None:
        if text == last_text["value"]:
            return
        last_text["value"] = text
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
        except Exception as e:
            log.debug("status_edit_failed", error=str(e))

    return _emit


async def _run_voice_pipeline(
    *,
    audio_bytes: bytes,
    chat_id: int,
    ack_message_id: int,
    bot,
    update_id: int | None = None,
) -> None:
    started = time.perf_counter()
    status = _make_status_editor(bot, chat_id, ack_message_id)
    try:
        result = await orchestrator.process_voice(
            audio_bytes,
            tg_chat_id=chat_id,
            tg_message_id=ack_message_id,
            drive=_drive_or_none(),
            status=status,
        )
    except Exception as e:
        # Surface the real exception class + update_id to Telegram so the
        # owner can correlate the failure end-to-end without server logs.
        # The legacy "TRANSCRIBE_FAILED" copy was misleading — the same path
        # also catches DB/structuring/Drive failures.
        log.exception("voice_pipeline_failed", error=str(e))
        await bot.send_message(
            chat_id=chat_id,
            text=replies.error_message(error=e, update_id=update_id),
        )
        return

    text = (
        replies.format_full_bundle(result.entry)
        if not result.needs_structuring
        else f"{result.entry.transcript}\n\n{replies.NEEDS_STRUCTURING}\n🆔 {result.entry.short_id}"
    )
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=ack_message_id, text=text)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=text)
    log.info(
        "voice_reply_sent",
        short_id=result.entry.short_id,
        needs_structuring=result.needs_structuring,
        total_seconds=time.perf_counter() - started,
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _bind_request_context(update)
    if _require_user(update) is None:
        log.info("text_refused", reason="not_allowed")
        await _refuse(update)
        return
    if not update.message or not update.message.text:
        return

    body = update.message.text.strip()
    if not body:
        return

    pending = state.peek_pending(update.effective_chat.id)
    if pending is not None:
        log.info("pending_action_resume", kind=pending.kind, short_id=pending.short_id)
        await _handle_pending(update, body, pending)
        return

    log.info("text_received", chars=len(body))
    ack = await update.message.reply_text(replies.ACK_TEXT)

    await _run_text_pipeline(
        text=body,
        chat_id=update.effective_chat.id,
        ack_message_id=ack.message_id,
        bot=context.bot,
        update_id=getattr(update, "update_id", None),
    )


async def _run_text_pipeline(
    *,
    text: str,
    chat_id: int,
    ack_message_id: int,
    bot,
    update_id: int | None = None,
) -> None:
    status = _make_status_editor(bot, chat_id, ack_message_id)
    try:
        result = await orchestrator.process_text(
            text,
            tg_chat_id=chat_id,
            tg_message_id=ack_message_id,
            drive=_drive_or_none(),
            status=status,
        )
    except Exception as e:
        # See _run_voice_pipeline: surface the real error class to Telegram
        # instead of the misleading "NEEDS_STRUCTURING" copy.
        log.exception("text_pipeline_failed", error=str(e))
        await bot.send_message(
            chat_id=chat_id,
            text=replies.error_message(error=e, update_id=update_id),
        )
        return

    out = (
        replies.format_full_bundle(result.entry)
        if not result.needs_structuring
        else f"{replies.NEEDS_STRUCTURING}\n🆔 {result.entry.short_id}"
    )
    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=ack_message_id, text=out)
    except Exception:
        await bot.send_message(chat_id=chat_id, text=out)


async def _handle_pending(update: Update, body: str, pending: state.PendingAction) -> None:
    chat_id = update.effective_chat.id
    state.pop_pending(chat_id)
    if pending.kind == "edit":
        async with session_scope() as session:
            entry = await repo.get_by_short_id(session, pending.short_id)
            if entry is None:
                await update.message.reply_text(replies.NOT_FOUND)
                return
            await repo.update_entry(session, entry, transcript=body, status="editing")
        result = await structure_with_retry(body)
        async with session_scope() as session:
            fresh = await repo.get_by_short_id(session, pending.short_id)
            if fresh is None:
                await update.message.reply_text(replies.NOT_FOUND)
                return
            if result:
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
            else:
                await repo.update_entry(session, fresh, status="needs_structuring")
            done = fresh
        await update.message.reply_text(replies.format_full_bundle(done))
    elif pending.kind == "tags":
        new_tags = [t.strip() for t in body.split(",") if t.strip()]
        async with session_scope() as session:
            entry = await repo.get_by_short_id(session, pending.short_id)
            if entry is None:
                await update.message.reply_text(replies.NOT_FOUND)
                return
            await repo.update_entry(session, entry, tags=new_tags)
            done = entry
        await update.message.reply_text(replies.format_tags(done))


# ----- request-correlation + error handler -----


def _bind_request_context(update: Update) -> None:
    """Bind structlog context vars so every log line for this update shares a key.

    Uses Telegram's `update_id` plus `chat_id` / `user_id` so a single
    voice can be grepped end-to-end with e.g. `rg update_id=128258000`.
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        update_id=getattr(update, "update_id", None),
        chat_id=update.effective_chat.id if update.effective_chat else None,
        user_id=update.effective_user.id if update.effective_user else None,
    )


async def handle_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Global PTB error handler: logs richly + sends a generic Hebrew reply."""
    update_id = getattr(update, "update_id", None)
    eff_chat = getattr(update, "effective_chat", None)
    eff_user = getattr(update, "effective_user", None)
    chat_id = getattr(eff_chat, "id", None) if eff_chat is not None else None
    user_id = getattr(eff_user, "id", None) if eff_user is not None else None
    msg = getattr(update, "message", None)

    err = context.error
    log.exception(
        "handler_error",
        update_id=update_id,
        chat_id=chat_id,
        user_id=user_id,
        error_class=type(err).__name__ if err else None,
        error=str(err) if err else None,
        exc_info=err,
    )

    if chat_id is None:
        return

    text = replies.error_message(error=err, update_id=update_id)
    try:
        if msg is not None:
            await msg.reply_text(text)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text)
    except Exception as reply_err:
        log.warning(
            "handler_error_reply_failed",
            error=str(reply_err),
            error_class=type(reply_err).__name__,
        )


# ----- registration -----


def register(app: Application) -> None:
    # Group -1 runs before every other group. Non-allowlisted users are
    # refused here and never reach the command/voice handlers.
    app.add_handler(TypeHandler(Update, _allowlist_gate), group=-1)

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("last", cmd_last))
    app.add_handler(CommandHandler("show", cmd_show))
    app.add_handler(CommandHandler("questions", cmd_questions))
    app.add_handler(CommandHandler("edit", cmd_edit))
    app.add_handler(CommandHandler("tags", cmd_tags))
    app.add_handler(CommandHandler("restructure", cmd_restructure))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("usage", cmd_usage))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(handle_error)
