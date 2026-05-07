"""Smoke test that the package imports cleanly."""

from __future__ import annotations


def test_imports() -> None:
    import app
    from app import auth, background, config, idempotency, main  # noqa: F401
    from app.bot import application, handlers, replies, state  # noqa: F401
    from app.obs import usage  # noqa: F401
    from app.pipeline import orchestrator, prompts, structure, transcribe  # noqa: F401
    from app.store import db, drive, models, repo, short_id  # noqa: F401

    assert app.__version__
