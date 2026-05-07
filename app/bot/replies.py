"""Hebrew reply templates. Neutral, clear tone."""

from __future__ import annotations

from app.store.models import Entry

ACK_VOICE = "מקבל ומתמלל…"
ACK_TEXT = "מעבד…"
NOT_ALLOWED = "הבוט הזה פרטי."
NOT_FOUND = "לא נמצא רישום עם המזהה הזה."
NEEDS_STRUCTURING = "התמליל נשמר, אך עיבוד הניתוח נכשל וננסה שוב ברקע."
TRANSCRIBE_FAILED = "שגיאה בתמלול. נסה שוב."
EDIT_PROMPT = "שלח את התמליל המתוקן בהודעה הבאה."
EDIT_DONE = "התמליל עודכן ומחדש את הניתוח."


# --- per-step status messages (shown by editing the ack message) ---
#
# Each emits a Hebrew status with its step number so the user always knows
# where the pipeline is. Stage 5 is replaced by the final formatted bundle
# from `format_full_bundle`.


def status_received(
    *,
    audio_seconds: float | None = None,
    file_size_bytes: int | None = None,
) -> str:
    """Stage 1 status. Prefer audio duration if known, fall back to file size."""
    if audio_seconds is not None and audio_seconds > 0:
        return f"1/5 קיבלתי ({audio_seconds:.1f}s)"
    if file_size_bytes is not None:
        kb = max(1, round(file_size_bytes / 1024))
        return f"1/5 קיבלתי ({kb}KB)"
    return "1/5 קיבלתי"


def status_transcribing() -> str:
    return "2/5 🎙️ מתמלל…"


def status_downloading_model() -> str:
    return "2/5 ⏬ מוריד מודל תמלול (פעם ראשונה, עד כמה דקות)…"


def status_loading_model() -> str:
    """Model files are already cached locally — just need to load into RAM."""
    return "2/5 ⏳ טוען מודל תמלול מהמטמון (כמה שניות)…"


def status_transcribed(elapsed_seconds: float, chars: int) -> str:
    return f"3/5 ✅ תומלל ({elapsed_seconds:.1f}s, {chars} תווים)"


def status_saving() -> str:
    return "4/5 💾 שומר…"


def status_structuring() -> str:
    return "4/5 🧠 מנתח…"


def error_message() -> str:
    return "שגיאה זמנית. נסה שוב."


# --- backwards-compatible constants used elsewhere (orchestrator) ---
# Kept so callers that don't yet pass timing info still get a Hebrew status.

STATUS_DOWNLOADING_MODEL = status_downloading_model()
STATUS_TRANSCRIBING = status_transcribing()
STATUS_STRUCTURING = status_structuring()
STATUS_SAVING = status_saving()

START = (
    "שלום! זהו בוט הביוגרפיה האישי שלך.\n"
    "שלח לי הודעה קולית בעברית — אתמלל, אסכם, אתייג ואשאל שאלות המשך.\n"
    "פקודות: /last /show <id> /questions /edit <id> /tags <id> /restructure <id> "
    "/search <text> /usage /help"
)

HELP = (
    "פקודות:\n"
    "• /last — הרישום האחרון\n"
    "• /show <id> — מציג רישום\n"
    "• /questions — שאלות ההמשך האחרונות\n"
    "• /edit <id> — עריכת תמליל ידנית\n"
    "• /tags <id> — דריסת תגיות\n"
    "• /restructure <id> — הרצה חוזרת של ה-LLM\n"
    "• /search <text> — חיפוש בתמלילים\n"
    "• /usage — שימוש מצטבר היום"
)


def format_full_bundle(entry: Entry) -> str:
    """The standard reply after a successful pipeline run."""
    tags = ", ".join(entry.tags or []) or "—"
    questions = entry.follow_up_questions or []
    q_lines = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions)) or "—"
    summary = entry.summary or "—"
    return (
        f"📝 התמליל\n{entry.transcript or '—'}\n\n"
        f"📌 תקציר\n{summary}\n\n"
        f"🏷 תגיות: {tags}\n\n"
        f"❓ שאלות המשך:\n{q_lines}\n\n"
        f"🆔 {entry.short_id}"
    )


def format_compact(entry: Entry) -> str:
    tags = ", ".join(entry.tags or []) or "—"
    return f"📌 {entry.summary or '—'}\n🏷 {tags}\n🆔 {entry.short_id}"


def format_questions(entry: Entry) -> str:
    qs = entry.follow_up_questions or []
    if not qs:
        return "אין שאלות המשך לרישום הזה."
    body = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(qs))
    return f"❓ שאלות המשך לרישום {entry.short_id}:\n{body}"


def format_search_results(entries: list[Entry]) -> str:
    if not entries:
        return "לא נמצאו תוצאות."
    lines = []
    for e in entries:
        snippet = (e.transcript or "")[:120].replace("\n", " ")
        lines.append(f"🆔 {e.short_id} — {snippet}…")
    return "\n".join(lines)


def format_tags(entry: Entry) -> str:
    tags = ", ".join(entry.tags or []) or "—"
    return f"🏷 תגיות לרישום {entry.short_id}: {tags}\nשלח רשימת תגיות מופרדות בפסיקים כדי לדרוס."
