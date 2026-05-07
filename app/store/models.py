"""SQLModel tables for entries and usage events."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Column, DateTime, Numeric
from sqlmodel import Field, SQLModel

from app.store.types import GUID, TextArray

# Fixed tag vocabulary — must match prompts.STRUCTURING_PROMPT.
TAG_VOCABULARY: tuple[str, ...] = (
    "childhood",
    "family",
    "school",
    "army",
    "career",
    "relationships",
    "health",
    "travel",
    "milestones",
    "daily_life",
)

# Status / source / kind values are stored as plain strings for flexibility.
ENTRY_STATUSES = ("ok", "needs_structuring", "editing")
ENTRY_SOURCES = ("voice", "text")
USAGE_KINDS = ("transcribe", "structure")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Entry(SQLModel, table=True):
    """One memory: transcript + structured fields."""

    __tablename__ = "entries"

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(GUID(), primary_key=True),
    )
    short_id: str = Field(index=True, unique=True, max_length=12)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )

    source: str = Field(default="voice", max_length=10)
    parent_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(GUID(), nullable=True, index=True),
    )

    transcript: str = Field(default="")
    summary: str | None = Field(default=None)

    tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(TextArray(), nullable=False),
    )
    entities: list[str] = Field(
        default_factory=list,
        sa_column=Column(TextArray(), nullable=False),
    )
    follow_up_questions: list[str] = Field(
        default_factory=list,
        sa_column=Column(TextArray(), nullable=False),
    )

    approx_age: int | None = Field(default=None)
    year: int | None = Field(default=None)

    status: str = Field(default="ok", max_length=24, index=True)

    drive_json_id: str | None = Field(default=None, max_length=200)
    drive_text_id: str | None = Field(default=None, max_length=200)

    tg_message_id: int | None = Field(default=None)
    tg_chat_id: int | None = Field(default=None)


class UsageEvent(SQLModel, table=True):
    """Per-call cost tracking (transcription seconds, LLM tokens)."""

    __tablename__ = "usage_events"

    id: int | None = Field(default=None, primary_key=True)
    created_at: datetime = Field(
        default_factory=_utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True),
    )
    kind: str = Field(max_length=24)
    seconds: Decimal | None = Field(
        default=None,
        sa_column=Column(Numeric(10, 3), nullable=True),
    )
    tokens_in: int | None = Field(default=None)
    tokens_out: int | None = Field(default=None)
    cost_usd: Decimal = Field(
        default=Decimal("0"),
        sa_column=Column(Numeric(10, 6), nullable=False),
    )
    entry_id: uuid.UUID | None = Field(
        default=None,
        sa_column=Column(GUID(), nullable=True, index=True),
    )
