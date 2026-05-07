"""Repo CRUD against in-memory SQLite."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.store import repo


@pytest.mark.asyncio
async def test_create_and_get_entry(session, fixed_short_id) -> None:
    entry = await repo.create_entry(session, transcript="שלום", source="text")
    assert entry.short_id == "AAAAAA"
    assert entry.transcript == "שלום"

    fetched = await repo.get_by_short_id(session, "AAAAAA")
    assert fetched is not None
    assert fetched.id == entry.id


@pytest.mark.asyncio
async def test_get_last_returns_most_recent(session, fixed_short_id) -> None:
    await repo.create_entry(session, transcript="ראשון")
    await repo.create_entry(session, transcript="שני")
    last = await repo.get_last(session)
    assert last is not None
    assert last.transcript == "שני"


@pytest.mark.asyncio
async def test_search_transcript_finds_substring(session, fixed_short_id) -> None:
    await repo.create_entry(session, transcript="זיכרון מילדות בחיפה")
    await repo.create_entry(session, transcript="שירות בצבא")
    hits = await repo.search_transcript(session, "חיפה")
    assert len(hits) == 1
    assert "חיפה" in hits[0].transcript


@pytest.mark.asyncio
async def test_record_usage_aggregates(session, fixed_short_id) -> None:
    from app.store.repo import utc_n_days_ago

    await repo.record_usage(
        session,
        kind="structure",
        cost_usd=Decimal("0.001234"),
        tokens_in=100,
        tokens_out=50,
    )
    await repo.record_usage(
        session,
        kind="transcribe",
        cost_usd=Decimal("0"),
        seconds=Decimal("12.5"),
    )
    totals = await repo.usage_since(session, utc_n_days_ago(1))
    assert totals["events"] == 2
    assert totals["tokens_in"] == 100
    assert totals["tokens_out"] == 50
    assert totals["cost_usd"] == Decimal("0.001234")


@pytest.mark.asyncio
async def test_list_pending_structuring(session, fixed_short_id) -> None:
    await repo.create_entry(session, transcript="ok-entry", status="ok")
    await repo.create_entry(session, transcript="needs-it", status="needs_structuring")
    pending = await repo.list_pending_structuring(session)
    assert len(pending) == 1
    assert pending[0].transcript == "needs-it"
