"""Local filesystem store: persist transcripts and structured JSON to disk."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)


@dataclass
class LocalStore:
    """Saves biography entries to a local directory instead of Google Drive."""

    output_dir: Path = field(default_factory=lambda: Path("./biography_output"))

    @classmethod
    def from_settings(cls) -> LocalStore:
        s = get_settings()
        configured = Path(s.output_dir)
        # On serverless platforms only `/tmp` is writable. If the configured
        # path is a relative project path, redirect under `/tmp` so writes
        # don't fail on read-only filesystems.
        if s.is_serverless and not str(configured).startswith("/tmp"):
            configured = Path("/tmp") / "biography_output"
        return cls(output_dir=configured)

    async def save_transcript(self, short_id: str, text: str) -> str:
        """Write a plain-text transcript to disk. Returns the file path."""

        def _do() -> str:
            path = self.output_dir / "text" / f"{short_id}.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            return str(path)

        file_path = await asyncio.to_thread(_do)
        log.info("local_saved_transcript", short_id=short_id, path=file_path)
        return file_path

    async def save_entry_json(self, short_id: str, payload: dict[str, Any]) -> str:
        """Write the structured JSON payload to disk. Returns the file path."""

        def _do() -> str:
            path = self.output_dir / "entries" / f"{short_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return str(path)

        file_path = await asyncio.to_thread(_do)
        log.info("local_saved_entry_json", short_id=short_id, path=file_path)
        return file_path
