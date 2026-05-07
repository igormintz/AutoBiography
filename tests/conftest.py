"""Shared pytest fixtures: in-memory SQLite for fast unit tests."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

# Default env vars before importing app modules.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test-secret")
os.environ.setdefault("ALLOWED_TG_USER_IDS", "111,222")
os.environ.setdefault("OPENAI_API_KEY", "sk-test")
os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_JSON", "")
os.environ.setdefault("GOOGLE_DRIVE_FOLDER_ID", "")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("HF_HOME", "./.hf-cache")


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Fresh in-memory SQLite session per test.

    The schema uses cross-dialect TypeDecorators (`TextArray`, `GUID`) defined
    in `app.store.types`, so SQLModel.metadata.create_all works directly
    against SQLite — no monkey-patching required.
    """
    from app.store import models  # noqa: F401  (register tables)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    async with maker() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def fixed_short_id(monkeypatch):
    """Force make_short_id() to return predictable values."""
    seq = iter(["AAAAAA", "BBBBBB", "CCCCCC", "DDDDDD", "EEEEEE"])
    monkeypatch.setattr("app.store.repo.make_short_id", lambda: next(seq))
    return seq
