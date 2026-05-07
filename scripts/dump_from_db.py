"""Pull every entry from Postgres into the local `biography_output/` layout.

Usage::

    # Use settings from .env (DATABASE_URL + OUTPUT_DIR)
    uv run python scripts/dump_from_db.py

    # Override either inline:
    DATABASE_URL=postgresql+asyncpg://user:pw@host/db \\
        uv run python scripts/dump_from_db.py --output-dir ./prod_dump

    # Or via flag:
    uv run python scripts/dump_from_db.py \\
        --database-url postgresql+asyncpg://user:pw@host/db \\
        --output-dir ./prod_dump

After it finishes you'll have::

    <output-dir>/text/<short_id>.txt        # plain transcripts
    <output-dir>/entries/<short_id>.json    # structured payloads

…matching exactly what the live local pipeline writes.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `uv run python scripts/dump_from_db.py` from the project root
# without requiring the project to be installed as a package.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.logging import configure_logging, get_logger  # noqa: E402
from app.store.export import dump_entries  # noqa: E402

log = get_logger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL (otherwise read from settings/.env).",
    )
    p.add_argument(
        "--output-dir",
        default=None,
        help="Where to write files (otherwise use settings.output_dir, default ./biography_output).",
    )
    return p.parse_args()


async def _run(database_url: str, output_dir: Path) -> dict[str, int]:
    engine = create_async_engine(database_url, echo=False, pool_pre_ping=True, future=True)
    maker = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with maker() as session:
            return await dump_entries(session, output_dir)
    finally:
        await engine.dispose()


def main() -> None:
    configure_logging()
    args = _parse_args()
    settings = get_settings()

    database_url = args.database_url or settings.database_url
    output_dir = Path(args.output_dir or settings.output_dir)

    log.info("dump_start", database_url=_redact(database_url), output_dir=str(output_dir))
    counts = asyncio.run(_run(database_url, output_dir))
    print(
        f"Wrote {counts['entries']} entries ({counts['transcripts']} transcripts) to {output_dir}"
    )


def _redact(url: str) -> str:
    """Strip credentials from a DB URL for logging."""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    if "@" in rest:
        _, host = rest.split("@", 1)
        return f"{scheme}://***@{host}"
    return url


if __name__ == "__main__":
    main()
