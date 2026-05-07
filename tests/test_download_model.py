"""Build-time helper that pre-fetches the Whisper model into HF_HOME."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "download_model.py"


def _load_script() -> ModuleType:
    """Import `scripts/download_model.py` as a module without a package init."""
    sys.modules.pop("download_model", None)
    spec = importlib.util.spec_from_file_location("download_model", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_download_model_calls_snapshot_download_with_env_settings(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`download_model.main()` should fetch the configured repo into HF_HOME."""
    monkeypatch.setenv("WHISPER_MODEL", "ivrit-ai/whisper-large-v3-turbo-ct2")
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    fake_hub = MagicMock()
    fake_hub.snapshot_download = MagicMock(return_value=str(tmp_path / "snap"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    module = _load_script()
    module.main()

    fake_hub.snapshot_download.assert_called_once()
    kwargs = fake_hub.snapshot_download.call_args.kwargs
    assert kwargs["repo_id"] == "ivrit-ai/whisper-large-v3-turbo-ct2"
    assert kwargs["cache_dir"] == str(tmp_path)


def test_download_model_uses_default_repo_when_unset(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("WHISPER_MODEL", raising=False)
    monkeypatch.setenv("HF_HOME", str(tmp_path))

    fake_hub = MagicMock()
    fake_hub.snapshot_download = MagicMock(return_value=str(tmp_path / "snap"))
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake_hub)

    module = _load_script()
    module.main()

    kwargs = fake_hub.snapshot_download.call_args.kwargs
    assert kwargs["repo_id"] == "ivrit-ai/whisper-large-v3-turbo-ct2"
