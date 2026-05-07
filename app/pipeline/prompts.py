"""LLM prompts for structuring transcripts."""

from __future__ import annotations

from app.store.models import TAG_VOCABULARY

_TAG_LIST = ", ".join(TAG_VOCABULARY)

STRUCTURING_SYSTEM = f"""You are helping build a structured Hebrew autobiography database.

Given a Hebrew transcript of a personal memory, produce JSON with:
- summary: 1–2 sentence Hebrew summary, neutral and concise
- tags: choose only from this fixed list:
  {_TAG_LIST}
- entities: Hebrew names of people, places, and events mentioned in the
  transcript. Up to 10. Do not invent.
- timeline.approx_age: integer if implied, else null
- timeline.year: 4-digit year if explicit, else null
- follow_up_questions: 3–5 specific Hebrew questions that, if answered,
  would improve missing details, chronology, or significance. Avoid yes/no
  questions. Avoid generic prompts.

Do not invent facts. If a field is unknown, use null or an empty list.
Output Hebrew text in Hebrew. Output JSON keys in English.
"""


def user_prompt(transcript: str) -> str:
    """Format the user-facing message containing the transcript."""
    return f'Transcript:\n"""\n{transcript}\n"""'
