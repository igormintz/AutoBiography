"""Whisper model cache detection helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.pipeline import transcribe


def _patched_settings(tmp_path: Path) -> Settings:
    return Settings(
        hf_home=str(tmp_path),
        whisper_model="ivrit-ai/whisper-large-v3-turbo-ct2",
    )


def test_is_model_cached_on_disk_false_when_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transcribe, "get_settings", lambda: _patched_settings(tmp_path))
    assert transcribe.is_model_cached_on_disk() is False


def test_is_model_cached_on_disk_false_when_snapshots_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "models--ivrit-ai--whisper-large-v3-turbo-ct2" / "snapshots").mkdir(parents=True)
    monkeypatch.setattr(transcribe, "get_settings", lambda: _patched_settings(tmp_path))
    assert transcribe.is_model_cached_on_disk() is False


def test_is_model_cached_on_disk_true_when_snapshot_has_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snap = tmp_path / "models--ivrit-ai--whisper-large-v3-turbo-ct2" / "snapshots" / "abcdef"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"x")
    monkeypatch.setattr(transcribe, "get_settings", lambda: _patched_settings(tmp_path))
    assert transcribe.is_model_cached_on_disk() is True
