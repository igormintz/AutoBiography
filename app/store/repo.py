"""Repository helpers: CRUD over Entry and UsageEvent."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.store.models import Entry, UsageEvent
from app.store.short_id import make_short_id


async def create_entry(
    session: AsyncSession,
    *,
    transcript: str,
    source: str = "voice",
    parent_id: uuid.UUID | None = None,
    status: str = "ok",
    tg_chat_id: int | None = None,
    tg_message_id: int | None = None,
) -> Entry:
    """Insert a new Entry with a unique short_id."""
    # Retry a few times on collision (extremely unlikely with 6 chars from 30-symbol alphabet).
    for _ in range(5):
        short_id = make_short_id()
        existing = await session.execute(select(Entry).where(Entry.short_id == short_id))
        if existing.scalar_one_or_none() is None:
            break
    else:
        raise RuntimeError("Could not generate a unique short_id after 5 attempts")

    entry = Entry(
        short_id=short_id,
        transcript=transcript,
        source=source,
        parent_id=parent_id,
        status=status,
        tg_chat_id=tg_chat_id,
        tg_message_id=tg_message_id,
    )
    session.add(entry)
    await session.flush()
    return entry


async def get_by_short_id(session: AsyncSession, short_id: str) -> Entry | None:
    res = await session.execute(select(Entry).where(Entry.short_id == short_id.upper()))
    return res.scalar_one_or_none()


async def get_last(session: AsyncSession) -> Entry | None:
    res = await session.execute(select(Entry).order_by(desc(Entry.created_at)).limit(1))
    return res.scalar_one_or_none()


async def search_transcript(session: AsyncSession, term: str, limit: int = 5) -> list[Entry]:
    """Case-insensitive substring search over transcripts."""
    if not term.strip():
        return []
    pattern = f"%{term.strip()}%"
    res = await session.execute(
        select(Entry)
        .where(Entry.transcript.ilike(pattern))
        .order_by(desc(Entry.created_at))
        .limit(limit)
    )
    return list(res.scalars().all())


async def list_pending_structuring(session: AsyncSession, limit: int = 20) -> list[Entry]:
    res = await session.execute(
        select(Entry)
        .where(Entry.status == "needs_structuring")
        .order_by(Entry.created_at)
        .limit(limit)
    )
    return list(res.scalars().all())


async def update_entry(session: AsyncSession, entry: Entry, **fields) -> Entry:
    for k, v in fields.items():
        setattr(entry, k, v)
    session.add(entry)
    await session.flush()
    return entry


async def record_usage(
    session: AsyncSession,
    *,
    kind: str,
    cost_usd: Decimal,
    seconds: Decimal | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    entry_id: uuid.UUID | None = None,
) -> UsageEvent:
    event = UsageEvent(
        kind=kind,
        cost_usd=cost_usd,
        seconds=seconds,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        entry_id=entry_id,
    )
    session.add(event)
    await session.flush()
    return event


async def usage_since(session: AsyncSession, since: datetime) -> dict[str, Decimal | int]:
    """Aggregate usage since a UTC datetime. Returns totals for digest/usage commands."""
    res = await session.execute(select(UsageEvent).where(UsageEvent.created_at >= since))
    events = list(res.scalars().all())
    total_cost = sum((e.cost_usd or Decimal("0")) for e in events)
    total_seconds = sum((e.seconds or Decimal("0")) for e in events if e.kind == "transcribe")
    total_tokens_in = sum((e.tokens_in or 0) for e in events if e.kind == "structure")
    total_tokens_out = sum((e.tokens_out or 0) for e in events if e.kind == "structure")
    return {
        "events": len(events),
        "cost_usd": Decimal(total_cost),
        "transcribe_seconds": Decimal(total_seconds),
        "tokens_in": int(total_tokens_in),
        "tokens_out": int(total_tokens_out),
    }


def utc_day_start(now: datetime | None = None) -> datetime:
    """Start of today (UTC) — for daily aggregations."""
    now = now or datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def utc_n_days_ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)
