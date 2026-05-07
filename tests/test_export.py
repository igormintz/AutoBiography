"""Tests for `app.store.export` — Postgres → local-disk dump."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.store import repo
from app.store.export import dump_entries, entry_to_payload


@pytest.mark.asyncio
async def test_entry_to_payload_structured(session, fixed_short_id) -> None:
    entry = await repo.create_entry(session, transcript="עליתי לארץ בגיל חמש", source="voice")
    await repo.update_entry(
        session,
        entry,
        summary="עליה לארץ בגיל חמש",
        tags=["family", "milestones"],
        entities=["ארץ"],
        approx_age=5,
        year=1991,
        follow_up_questions=["מה הסיבה?"],
    )

    payload = entry_to_payload(entry)

    assert payload["short_id"] == "AAAAAA"
    assert payload["source"] == "voice"
    assert payload["transcript"] == "עליתי לארץ בגיל חמש"
    assert payload["summary"] == "עליה לארץ בגיל חמש"
    assert payload["tags"] == ["family", "milestones"]
    assert payload["entities"] == ["ארץ"]
    assert payload["timeline"] == {"approx_age": 5, "year": 1991}
    assert payload["follow_up_questions"] == ["מה הסיבה?"]
    # `created_at` should be ISO-8601, parseable.
    assert "T" in payload["created_at"]
    # `id` should be a string, not a UUID object — JSON-serializable.
    assert isinstance(payload["id"], str)


@pytest.mark.asyncio
async def test_entry_to_payload_unstructured(session, fixed_short_id) -> None:
    entry = await repo.create_entry(session, transcript="טקסט גולמי", status="needs_structuring")

    payload = entry_to_payload(entry)

    assert payload["summary"] is None
    assert payload["tags"] == []
    assert payload["entities"] == []
    assert payload["follow_up_questions"] == []
    assert payload["timeline"] == {"approx_age": None, "year": None}


@pytest.mark.asyncio
async def test_dump_entries_writes_text_and_json(session, fixed_short_id, tmp_path: Path) -> None:
    entry = await repo.create_entry(session, transcript="זיכרון אחד", source="voice")
    await repo.update_entry(session, entry, summary="סיכום", tags=["childhood"])
    await repo.create_entry(session, transcript="זיכרון שני", source="text")

    counts = await dump_entries(session, tmp_path)

    assert counts == {"entries": 2, "transcripts": 2}

    # Both transcripts written verbatim.
    assert (tmp_path / "text" / "AAAAAA.txt").read_text(encoding="utf-8") == "זיכרון אחד"
    assert (tmp_path / "text" / "BBBBBB.txt").read_text(encoding="utf-8") == "זיכרון שני"

    # Both JSON entries written, parseable, with the expected shape.
    payload = json.loads((tmp_path / "entries" / "AAAAAA.json").read_text(encoding="utf-8"))
    assert payload["short_id"] == "AAAAAA"
    assert payload["summary"] == "סיכום"
    assert payload["tags"] == ["childhood"]


@pytest.mark.asyncio
async def test_dump_entries_skips_blank_transcripts(
    session, fixed_short_id, tmp_path: Path
) -> None:
    """An entry with an empty transcript should not produce a `text/*.txt` file,
    but should still produce a JSON file (so the row isn't lost)."""
    await repo.create_entry(session, transcript="", source="text")

    counts = await dump_entries(session, tmp_path)

    assert counts == {"entries": 1, "transcripts": 0}
    assert not (tmp_path / "text" / "AAAAAA.txt").exists()
    assert (tmp_path / "entries" / "AAAAAA.json").exists()


@pytest.mark.asyncio
async def test_dump_entries_creates_output_dirs(session, fixed_short_id, tmp_path: Path) -> None:
    """Output dir should be created if it doesn't exist."""
    target = tmp_path / "fresh" / "nested"
    await repo.create_entry(session, transcript="hi", source="text")

    await dump_entries(session, target)

    assert (target / "text").is_dir()
    assert (target / "entries").is_dir()
