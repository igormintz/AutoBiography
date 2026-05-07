"""Structuring with mocked OpenAI."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.pipeline import structure


@pytest.fixture(autouse=True)
def reset_client():
    structure.reset_client_for_tests()
    yield
    structure.reset_client_for_tests()


def _fake_openai(parsed: structure.Structured, tokens_in: int = 100, tokens_out: int = 50):
    """Build a fake AsyncOpenAI client whose .beta.chat.completions.parse returns parsed."""
    fake = SimpleNamespace()
    fake.beta = SimpleNamespace()
    fake.beta.chat = SimpleNamespace()
    fake.beta.chat.completions = SimpleNamespace()

    async def parse(**kwargs):
        msg = SimpleNamespace(parsed=parsed)
        choice = SimpleNamespace(message=msg)
        usage = SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out)
        return SimpleNamespace(choices=[choice], usage=usage)

    fake.beta.chat.completions.parse = parse
    return fake


@pytest.mark.asyncio
async def test_structure_returns_parsed_payload(monkeypatch) -> None:
    parsed = structure.Structured(
        summary="זיכרון מילדות בחיפה.",
        tags=["childhood", "family"],
        entities=["חיפה", "סבתא"],
        timeline=structure.Timeline(approx_age=7, year=1990),
        follow_up_questions=[
            "מי עוד היה שם?",
            "באיזו שכונה?",
            "מה הרגשת?",
        ],
    )
    monkeypatch.setattr(structure, "get_client", lambda: _fake_openai(parsed))

    result = await structure.structure_transcript("טקסט עברית")
    assert result.data == parsed
    assert result.tokens_in == 100
    assert result.tokens_out == 50
    assert result.cost_usd > Decimal("0")


@pytest.mark.asyncio
async def test_structure_with_retry_returns_none_after_failures(monkeypatch) -> None:
    calls = {"n": 0}

    fake = SimpleNamespace()
    fake.beta = SimpleNamespace()
    fake.beta.chat = SimpleNamespace()
    fake.beta.chat.completions = SimpleNamespace()

    async def boom(**kwargs):
        calls["n"] += 1
        raise ValueError("simulated bad json")

    fake.beta.chat.completions.parse = boom
    monkeypatch.setattr(structure, "get_client", lambda: fake)

    result = await structure.structure_with_retry("טקסט", max_attempts=3)
    assert result is None
    assert calls["n"] == 3


def test_unknown_tags_dropped() -> None:
    s = structure.Structured(
        summary="x",
        tags=["family", "not_a_real_tag"],
        entities=[],
        timeline=structure.Timeline(),
        follow_up_questions=["a?", "b?", "c?"],
    )
    assert "not_a_real_tag" not in s.tags
    assert "family" in s.tags
