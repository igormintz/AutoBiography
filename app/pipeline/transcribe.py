"""Hebrew speech-to-text.

Two backends, picked at runtime:

1. **Local `faster-whisper`** with `ivrit-ai/whisper-large-v3-turbo-ct2` —
   default for self-hosted (Railway/Docker) where we have GPU/CPU and disk.
2. **OpenAI Whisper API** (`whisper-1`) — used when `faster-whisper` isn't
   installed or refuses to load (which is the case on Vercel: the model
   weights and runtime exceed serverless bundle limits).
"""

from __future__ import annotations

import asyncio
import io
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)

# Lazy globals so importing this module doesn't trigger a multi-GB model download.
_model: Any | None = None
_async_openai_client: Any | None = None


@dataclass(frozen=True)
class TranscribeResult:
    text: str
    seconds_audio: float
    seconds_compute: float


def _load_model():
    """Construct a faster-whisper model. Imported lazily so tests can mock it out.

    Raises ModuleNotFoundError when the optional `faster-whisper` extra isn't
    installed (e.g. on Vercel).
    """
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]

    settings = get_settings()
    os.makedirs(settings.hf_home, exist_ok=True)
    log.info(
        "loading_whisper_model",
        model=settings.whisper_model,
        device=settings.whisper_device,
        compute=settings.whisper_compute,
        download_root=settings.hf_home,
    )
    return WhisperModel(
        settings.whisper_model,
        device=settings.whisper_device,
        compute_type=settings.whisper_compute,
        download_root=settings.hf_home,
    )


def get_model():
    """Return the global Whisper model, loading it on first call.

    Returns None if faster-whisper isn't available — callers should fall back
    to `transcribe_with_openai`.
    """
    global _model
    if _model is None:
        try:
            _model = _load_model()
        except ModuleNotFoundError:
            log.info("faster_whisper_unavailable_using_openai_fallback")
            return None
    return _model


def is_model_loaded() -> bool:
    """True iff the Whisper model has already been initialized in this process."""
    return _model is not None


def is_model_cached_on_disk() -> bool:
    """True iff the HuggingFace cache already contains a downloaded snapshot.

    Checks for a non-empty `snapshots/<commit>/` directory under
    `<hf_home>/models--<owner>--<name>/`.
    """
    settings = get_settings()
    repo_dir = settings.whisper_model.replace("/", "--")
    snapshots = Path(settings.hf_home) / f"models--{repo_dir}" / "snapshots"
    if not snapshots.is_dir():
        return False
    return any(child.is_dir() and any(child.iterdir()) for child in snapshots.iterdir())


def reset_model_for_tests() -> None:
    """Test helper: drop the cached model so a fresh patched one is used."""
    global _model, _async_openai_client
    _model = None
    _async_openai_client = None


def _openai_client():
    """Return a cached AsyncOpenAI client, or None if no API key is configured."""
    global _async_openai_client
    if _async_openai_client is not None:
        return _async_openai_client
    api_key = get_settings().openai_api_key
    if not api_key:
        return None
    from openai import AsyncOpenAI

    _async_openai_client = AsyncOpenAI(api_key=api_key)
    return _async_openai_client


async def _transcribe_with_openai(audio_bytes: bytes, *, language: str) -> TranscribeResult:
    """Hebrew transcription via OpenAI's `audio.transcriptions` endpoint."""
    client = _openai_client()
    if client is None:
        log.warning("openai_whisper_skipped_no_api_key")
        return TranscribeResult(text="", seconds_audio=0.0, seconds_compute=0.0)

    started = time.perf_counter()
    buf = io.BytesIO(audio_bytes)
    buf.name = "audio.ogg"  # SDK uses the filename to infer the mime type.

    response = await client.audio.transcriptions.create(
        model=get_settings().openai_whisper_model,
        file=buf,
        language=language,
        response_format="verbose_json",
    )
    elapsed = time.perf_counter() - started

    text = (getattr(response, "text", "") or "").strip()
    duration = float(getattr(response, "duration", 0.0) or 0.0)
    log.info(
        "openai_transcription_complete",
        chars=len(text),
        audio_seconds=duration,
        compute_seconds=elapsed,
    )
    return TranscribeResult(text=text, seconds_audio=duration, seconds_compute=elapsed)


def _transcribe_with_local_model(audio_bytes: bytes, *, language: str) -> TranscribeResult:
    started = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=True) as f:
        f.write(audio_bytes)
        f.flush()
        model = get_model()
        if model is None:
            return TranscribeResult(text="", seconds_audio=0.0, seconds_compute=0.0)
        segments, info = model.transcribe(
            f.name,
            language=language,
            vad_filter=True,
            beam_size=5,
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
    elapsed = time.perf_counter() - started

    audio_seconds = float(getattr(info, "duration", 0.0) or 0.0)
    log.info(
        "transcription_complete",
        chars=len(text),
        audio_seconds=audio_seconds,
        compute_seconds=elapsed,
    )
    return TranscribeResult(
        text=text,
        seconds_audio=audio_seconds,
        seconds_compute=elapsed,
    )


def transcribe_bytes(audio_bytes: bytes, *, language: str = "he") -> TranscribeResult:
    """Transcribe raw audio bytes (e.g. an .ogg file) to a single string of Hebrew text.

    Picks faster-whisper when available, falls back to OpenAI's Whisper API
    otherwise. Synchronous so existing call-sites (`asyncio.to_thread(...)`)
    continue to work unchanged.
    """
    if not audio_bytes:
        return TranscribeResult(text="", seconds_audio=0.0, seconds_compute=0.0)

    try:
        model = get_model()
    except Exception as e:  # pragma: no cover — local model load failure
        log.warning("local_whisper_load_failed", error=str(e))
        model = None

    if model is not None:
        return _transcribe_with_local_model(audio_bytes, language=language)

    return asyncio.run(_transcribe_with_openai(audio_bytes, language=language))


def main() -> None:
    """CLI: `python -m app.pipeline.transcribe <file>`."""
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m app.pipeline.transcribe <audio-file>")
        sys.exit(1)
    path = sys.argv[1]
    with open(path, "rb") as f:
        data = f.read()
    result = transcribe_bytes(data)
    print(result.text)


if __name__ == "__main__":
    main()
