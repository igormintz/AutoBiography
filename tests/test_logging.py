"""configure_logging picks the right structlog renderer based on settings."""

from __future__ import annotations

import structlog

from app import logging as applog
from app.config import get_settings


def _renderer_class_names(processors: list) -> list[str]:
    return [p.__class__.__name__ for p in processors]


def test_configure_logging_default_uses_json_renderer(monkeypatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    get_settings.cache_clear()
    applog.configure_logging()
    cfg = structlog.get_config()
    names = _renderer_class_names(cfg["processors"])
    assert "JSONRenderer" in names
    assert "ConsoleRenderer" not in names


def test_configure_logging_console_uses_console_renderer(monkeypatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "console")
    get_settings.cache_clear()
    applog.configure_logging()
    cfg = structlog.get_config()
    names = _renderer_class_names(cfg["processors"])
    assert "ConsoleRenderer" in names
    assert "JSONRenderer" not in names
