"""End-to-end pipeline glue: transcribe → structure → persist → drive → reply."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from decimal import Decimal

from app.bot import replies
from app.config import get_settings
from app.logging import get_logger
from app.pipeline.structure import Structured, structure_with_retry
from app.pipeline.transcribe import is_model_loaded, transcribe_bytes
from app.store import repo
from app.store.db import session_scope
from app.store.local_store import LocalStore
from app.store.models import Entry

StatusCallback = Callable[[str], Awaitable[None]]

log = get_logger(__name__)


@dataclass
class PipelineResult:
    entry: Entry
    structured: Structured | None
    needs_structuring: bool


async def _emit(status: StatusCallback | None, message: str) -> None:
    if status is None:
        return
    try:
        await status(message)
    except Exception as e:
        log.debug("status_callback_failed", error=str(e))


async def process_voice(
    audio_bytes: bytes,
    *,
    tg_chat_id: int | None = None,
    tg_message_id: int | None = None,
    drive: LocalStore | None = None,
    status: StatusCallback | None = None,
) -> PipelineResult:
    """Transcribe Hebrew voice → structure → persist → save locally."""
    pipeline_started = time.perf_counter()
    log.info("pipeline_voice_start", bytes=len(audio_bytes))

    # The model weights are baked into the image at build time, so the only
    # cold-start cost is loading them into RAM. No need to probe the cache.
    if is_model_loaded():
        await _emit(status, replies.status_transcribing())
    else:
        await _emit(status, replies.status_loading_model())

    log.info("transcribe_start", model_loaded=is_model_loaded())
    transcribe_started = time.perf_counter()
    transcribe_result = await asyncio.to_thread(transcribe_bytes, audio_bytes)
    transcribe_elapsed = time.perf_counter() - transcribe_started
    log.info(
        "transcribe_done",
        chars=len(transcribe_result.text),
        audio_seconds=transcribe_result.seconds_audio,
        compute_seconds=transcribe_result.seconds_compute,
        wallclock_seconds=transcribe_elapsed,
    )

    await _emit(
        status,
        replies.status_transcribed(
            elapsed_seconds=transcribe_result.seconds_compute,
            chars=len(transcribe_result.text),
        ),
    )

    if transcribe_result.text.strip() and get_settings().openai_api_key:
        await _emit(status, replies.status_structuring())
    else:
        await _emit(status, replies.status_saving())

    result = await _persist_and_structure(
        transcript=transcribe_result.text,
        source="voice",
        seconds=Decimal(str(transcribe_result.seconds_audio)),
        tg_chat_id=tg_chat_id,
        tg_message_id=tg_message_id,
        drive=drive,
    )

    log.info(
        "pipeline_voice_done",
        short_id=result.entry.short_id,
        needs_structuring=result.needs_structuring,
        total_seconds=time.perf_counter() - pipeline_started,
    )
    return result


async def process_text(
    text: str,
    *,
    tg_chat_id: int | None = None,
    tg_message_id: int | None = None,
    drive: LocalStore | None = None,
    status: StatusCallback | None = None,
) -> PipelineResult:
    """Skip transcription; treat user-typed text as the transcript."""
    pipeline_started = time.perf_counter()
    log.info("pipeline_text_start", chars=len(text))

    if text.strip() and get_settings().openai_api_key:
        await _emit(status, replies.status_structuring())
    else:
        await _emit(status, replies.status_saving())

    result = await _persist_and_structure(
        transcript=text,
        source="text",
        seconds=None,
        tg_chat_id=tg_chat_id,
        tg_message_id=tg_message_id,
        drive=drive,
    )

    log.info(
        "pipeline_text_done",
        short_id=result.entry.short_id,
        needs_structuring=result.needs_structuring,
        total_seconds=time.perf_counter() - pipeline_started,
    )
    return result


async def _persist_and_structure(
    *,
    transcript: str,
    source: str,
    seconds: Decimal | None,
    tg_chat_id: int | None,
    tg_message_id: int | None,
    drive: LocalStore | None,
) -> PipelineResult:
    structure_started = time.perf_counter()
    structured_result = await structure_with_retry(transcript) if transcript.strip() else None
    if transcript.strip():
        log.info(
            "structure_done",
            ok=structured_result is not None,
            seconds=time.perf_counter() - structure_started,
        )

    db_started = time.perf_counter()
    async with session_scope() as session:
        entry = await repo.create_entry(
            session,
            transcript=transcript,
            source=source,
            status="ok" if structured_result else "needs_structuring",
            tg_chat_id=tg_chat_id,
            tg_message_id=tg_message_id,
        )

        if structured_result:
            data = structured_result.data
            await repo.update_entry(
                session,
                entry,
                summary=data.summary,
                tags=list(data.tags),
                entities=list(data.entities),
                approx_age=data.timeline.approx_age,
                year=data.timeline.year,
                follow_up_questions=list(data.follow_up_questions),
            )
            await repo.record_usage(
                session,
                kind="structure",
                cost_usd=structured_result.cost_usd,
                tokens_in=structured_result.tokens_in,
                tokens_out=structured_result.tokens_out,
                entry_id=entry.id,
            )

        if seconds is not None and seconds > 0:
            await repo.record_usage(
                session,
                kind="transcribe",
                cost_usd=Decimal("0"),  # CPU plan: no marginal cost
                seconds=seconds,
                entry_id=entry.id,
            )

        snapshot_entry = entry
    log.info(
        "entry_saved",
        short_id=snapshot_entry.short_id,
        status=snapshot_entry.status,
        seconds=time.perf_counter() - db_started,
    )

    if drive is not None and structured_result is not None:
        drive_started = time.perf_counter()
        try:
            text_id = await drive.save_transcript(snapshot_entry.short_id, transcript)
            json_id = await drive.save_entry_json(
                snapshot_entry.short_id,
                _entry_to_json(snapshot_entry, structured_result.data),
            )
            async with session_scope() as session:
                fresh = await repo.get_by_short_id(session, snapshot_entry.short_id)
                if fresh is not None:
                    await repo.update_entry(
                        session, fresh, drive_text_id=text_id, drive_json_id=json_id
                    )
            log.info(
                "drive_save_done",
                short_id=snapshot_entry.short_id,
                seconds=time.perf_counter() - drive_started,
            )
        except Exception as e:
            log.warning("drive_save_failed", error=str(e), short_id=snapshot_entry.short_id)

    return PipelineResult(
        entry=snapshot_entry,
        structured=structured_result.data if structured_result else None,
        needs_structuring=structured_result is None,
    )


def _entry_to_json(entry: Entry, structured: Structured) -> dict:
    return {
        "id": str(entry.id),
        "short_id": entry.short_id,
        "created_at": entry.created_at.isoformat(),
        "source": entry.source,
        "transcript": entry.transcript,
        "summary": structured.summary,
        "tags": list(structured.tags),
        "entities": list(structured.entities),
        "timeline": {
            "approx_age": structured.timeline.approx_age,
            "year": structured.timeline.year,
        },
        "follow_up_questions": list(structured.follow_up_questions),
    }


def serialize_entry(entry: Entry) -> str:
    """Helper for `/show` to dump an existing entry as pretty JSON."""
    payload = {
        "id": str(entry.id),
        "short_id": entry.short_id,
        "created_at": entry.created_at.isoformat(),
        "source": entry.source,
        "transcript": entry.transcript,
        "summary": entry.summary,
        "tags": list(entry.tags or []),
        "entities": list(entry.entities or []),
        "timeline": {"approx_age": entry.approx_age, "year": entry.year},
        "follow_up_questions": list(entry.follow_up_questions or []),
        "status": entry.status,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)
