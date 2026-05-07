"""Reply formatting helpers."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.bot import replies
from app.store.models import Entry


def _entry(**overrides) -> Entry:
    base = dict(
        id=uuid.uuid4(),
        short_id="ABC123",
        created_at=datetime.now(timezone.utc),
        source="voice",
        transcript="שלום זה תמליל לדוגמה",
        summary="זה תקציר.",
        tags=["family", "childhood"],
        entities=["חיפה"],
        follow_up_questions=["שאלה 1?", "שאלה 2?", "שאלה 3?"],
        approx_age=None,
        year=None,
        status="ok",
    )
    base.update(overrides)
    return Entry(**base)


def test_format_full_bundle_contains_all_sections() -> None:
    msg = replies.format_full_bundle(_entry())
    assert "📝 התמליל" in msg
    assert "📌 תקציר" in msg
    assert "🏷 תגיות" in msg
    assert "❓ שאלות המשך" in msg
    assert "🆔 ABC123" in msg


def test_format_compact_short() -> None:
    msg = replies.format_compact(_entry())
    assert "ABC123" in msg
    assert "📌" in msg


def test_format_questions_lists_questions() -> None:
    msg = replies.format_questions(_entry())
    assert "שאלה 1?" in msg
    assert "ABC123" in msg


def test_format_search_empty() -> None:
    assert replies.format_search_results([]) == "לא נמצאו תוצאות."


def test_format_search_truncates() -> None:
    long_e = _entry(transcript="א" * 500)
    msg = replies.format_search_results([long_e])
    assert "ABC123" in msg
    assert "…" in msg


# --- granular per-step status helpers ---


def test_status_received_includes_step_and_size_fallback() -> None:
    msg = replies.status_received(file_size_bytes=44225)
    assert msg.startswith("1/5")
    assert "43" in msg or "44" in msg
    assert "KB" in msg


def test_status_received_prefers_duration_over_size() -> None:
    msg = replies.status_received(audio_seconds=4.2, file_size_bytes=44225)
    assert msg.startswith("1/5")
    assert "4.2" in msg
    assert "s" in msg
    assert "KB" not in msg


def test_status_received_no_args_is_step_one() -> None:
    msg = replies.status_received()
    assert msg.startswith("1/5")


def test_status_transcribing_is_step_two() -> None:
    msg = replies.status_transcribing()
    assert msg.startswith("2/5")
    assert "מתמלל" in msg


def test_status_downloading_model_indicates_first_time() -> None:
    msg = replies.status_downloading_model()
    assert msg.startswith("2/5")
    assert "מודל" in msg


def test_status_loading_model_indicates_cache_load() -> None:
    msg = replies.status_loading_model()
    assert msg.startswith("2/5")
    assert "מודל" in msg
    assert "מטמון" in msg


def test_status_transcribed_includes_timing_and_chars() -> None:
    msg = replies.status_transcribed(elapsed_seconds=9.92, chars=41)
    assert msg.startswith("3/5")
    assert "9.9" in msg
    assert "41" in msg
    assert "תווים" in msg


def test_status_saving_is_step_four() -> None:
    msg = replies.status_saving()
    assert msg.startswith("4/5")


def test_status_structuring_is_step_four() -> None:
    msg = replies.status_structuring()
    assert msg.startswith("4/5")
    assert "מנתח" in msg


def test_error_message_is_short_hebrew() -> None:
    msg = replies.error_message()
    assert "שגיאה" in msg
