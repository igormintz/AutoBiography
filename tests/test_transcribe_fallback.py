"""OpenAI Whisper fallback used when faster-whisper isn't installed (e.g. on Vercel)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import Settings
from app.pipeline import transcribe


def test_transcribe_uses_local_model_when_available(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Local faster-whisper path is preferred when available (non-serverless default)."""
    transcribe.reset_model_for_tests()

    fake_segment = MagicMock()
    fake_segment.text = "  שלום עולם  "
    fake_info = MagicMock()
    fake_info.duration = 1.5

    fake_model = MagicMock()
    fake_model.transcribe = MagicMock(return_value=([fake_segment], fake_info))
    monkeypatch.setattr(transcribe, "_load_model", lambda: fake_model)
    monkeypatch.setattr(
        transcribe,
        "get_settings",
        lambda: Settings(hf_home=str(tmp_path)),
    )

    result = transcribe.transcribe_bytes(b"\x00\x01\x02")
    assert result.text == "שלום עולם"
    assert result.seconds_audio == 1.5


def test_transcribe_falls_back_to_openai_when_faster_whisper_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If faster-whisper import fails, we use OpenAI's audio.transcriptions API."""
    transcribe.reset_model_for_tests()

    def boom():
        raise ModuleNotFoundError("faster_whisper")

    monkeypatch.setattr(transcribe, "_load_model", boom)

    fake_response = MagicMock()
    fake_response.text = "שלום מהעננים"
    fake_response.duration = 2.0

    fake_client = MagicMock()
    fake_client.audio.transcriptions.create = AsyncMock(return_value=fake_response)

    monkeypatch.setattr(transcribe, "_openai_client", lambda: fake_client)
    monkeypatch.setattr(
        transcribe,
        "get_settings",
        lambda: Settings(openai_api_key="sk-test"),
    )

    result = transcribe.transcribe_bytes(b"\x00\x01\x02")
    assert result.text == "שלום מהעננים"
    assert result.seconds_audio == 2.0
    fake_client.audio.transcriptions.create.assert_awaited_once()


def test_transcribe_returns_empty_for_empty_audio() -> None:
    result = transcribe.transcribe_bytes(b"")
    assert result.text == ""
    assert result.seconds_audio == 0.0
