"""Background-task helpers."""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.background import next_daily_run


def test_next_daily_run_today_in_future() -> None:
    tz = ZoneInfo("Asia/Jerusalem")
    now = datetime(2026, 5, 6, 7, 0, tzinfo=tz)
    target = next_daily_run(now, time(hour=9), tz)
    assert target.hour == 9
    assert target.day == 6


def test_next_daily_run_rolls_to_tomorrow() -> None:
    tz = ZoneInfo("Asia/Jerusalem")
    now = datetime(2026, 5, 6, 10, 0, tzinfo=tz)
    target = next_daily_run(now, time(hour=9), tz)
    assert target.day == 7
