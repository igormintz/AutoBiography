"""Daily usage digest formatting + scheduling helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.store import repo
from app.store.db import session_scope


async def daily_digest_text() -> str:
    yesterday = datetime.now(timezone.utc) - timedelta(days=1)
    start = yesterday.replace(hour=0, minute=0, second=0, microsecond=0)
    async with session_scope() as session:
        totals_yesterday = await repo.usage_since(session, start)

        month_start = datetime.now(timezone.utc).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        totals_month = await repo.usage_since(session, month_start)

    return (
        "📊 אתמול\n"
        f"• אירועים: {totals_yesterday['events']}\n"
        f"• שניות תמלול: {totals_yesterday['transcribe_seconds']}\n"
        f"• טוקנים LLM: {int(totals_yesterday['tokens_in'])} ↓ / "
        f"{int(totals_yesterday['tokens_out'])} ↑\n"
        f"• עלות אתמול: ${Decimal(totals_yesterday['cost_usd']):.4f}\n"
        f"• עלות מצטברת חודש: ${Decimal(totals_month['cost_usd']):.4f}"
    )
