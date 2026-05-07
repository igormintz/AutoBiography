"""Dump every Entry from the database into the on-disk `biography_output/` layout.

This is the inverse of `app.store.local_store`: it reads from Postgres
(the durable source of truth) and writes the same `text/<short_id>.txt`
+ `entries/<short_id>.json` files that the live pipeline writes locally.

Used by `scripts/dump_from_db.py` to pull production data back to a laptop.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.store.models import Entry

log = get_logger(__name__)


def entry_to_payload(entry: Entry) -> dict[str, Any]:
    """Serialize an `Entry` row to the on-disk JSON shape.

    Mirrors `app.pipeline.orchestrator._entry_to_json` so dumped files are
    indistinguishable from files the live pipeline writes locally.
    """
    return {
        "id": str(entry.id),
        "short_id": entry.short_id,
        "created_at": entry.created_at.isoformat(),
        "source": entry.source,
        "transcript": entry.transcript,
        "summary": entry.summary,
        "tags": list(entry.tags or []),
        "entities": list(entry.entities or []),
        "timeline": {"approx_age": entry.approx_age, "year": entry.year},
        "follow_up_questions": list(entry.follow_up_questions or []),
    }


async def dump_entries(session: AsyncSession, output_dir: Path) -> dict[str, int]:
    """Write every entry to `<output_dir>/{text,entries}/<short_id>.{txt,json}`.

    Returns counts: ``{"entries": N, "transcripts": M}`` where ``M`` excludes
    rows with empty transcripts (typically pre-structuring placeholders).
    """
    output_dir = Path(output_dir)
    text_dir = output_dir / "text"
    entries_dir = output_dir / "entries"
    text_dir.mkdir(parents=True, exist_ok=True)
    entries_dir.mkdir(parents=True, exist_ok=True)

    res = await session.execute(select(Entry).order_by(Entry.created_at))
    rows = list(res.scalars().all())

    transcript_count = 0
    for entry in rows:
        if entry.transcript:
            (text_dir / f"{entry.short_id}.txt").write_text(entry.transcript, encoding="utf-8")
            transcript_count += 1

        payload = entry_to_payload(entry)
        (entries_dir / f"{entry.short_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    counts = {"entries": len(rows), "transcripts": transcript_count}
    log.info("dump_entries_done", output_dir=str(output_dir), **counts)
    return counts
