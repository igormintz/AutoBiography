"""LLM structuring of transcripts via OpenAI's parsed structured outputs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import httpx
from openai import APIConnectionError, APIError, AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.config import get_settings
from app.logging import get_logger
from app.pipeline.prompts import STRUCTURING_SYSTEM, user_prompt
from app.store.models import TAG_VOCABULARY

log = get_logger(__name__)

# Canonical tag set kept in sync with TAG_VOCABULARY in models.py.
# Declared as Literal explicitly so OpenAI's JSON-schema generator emits an enum.
TagName = Literal[
    "childhood",
    "family",
    "school",
    "army",
    "career",
    "relationships",
    "health",
    "travel",
    "milestones",
    "daily_life",
]


class Timeline(BaseModel):
    approx_age: int | None = None
    year: int | None = None


class Structured(BaseModel):
    """Schema returned by the structuring LLM."""

    summary: str = Field(..., description="1–2 sentence Hebrew summary")
    tags: list[TagName] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list, max_length=10)
    timeline: Timeline = Field(default_factory=Timeline)
    follow_up_questions: list[str] = Field(..., min_length=3, max_length=5)

    @field_validator("tags", mode="before")
    @classmethod
    def _drop_unknown_tags(cls, v: object) -> object:
        """Defensive: silently drop any tag the model invented despite the prompt."""
        if isinstance(v, list):
            return [t for t in v if isinstance(t, str) and t in TAG_VOCABULARY]
        return v


@dataclass(frozen=True)
class StructureResult:
    data: Structured
    tokens_in: int
    tokens_out: int
    cost_usd: Decimal


# gpt-4o-mini pricing (USD per 1M tokens), accurate as of plan date.
_PRICE_IN_PER_M = Decimal("0.15")
_PRICE_OUT_PER_M = Decimal("0.60")


def _estimate_cost(tokens_in: int, tokens_out: int) -> Decimal:
    return (
        Decimal(tokens_in) * _PRICE_IN_PER_M / Decimal(1_000_000)
        + Decimal(tokens_out) * _PRICE_OUT_PER_M / Decimal(1_000_000)
    ).quantize(Decimal("0.000001"))


_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _client


def reset_client_for_tests() -> None:
    global _client
    _client = None


async def structure_transcript(transcript: str) -> StructureResult:
    """Single attempt; raises on failure."""
    client = get_client()
    resp = await client.beta.chat.completions.parse(
        model=get_settings().openai_model,
        messages=[
            {"role": "system", "content": STRUCTURING_SYSTEM},
            {"role": "user", "content": user_prompt(transcript)},
        ],
        response_format=Structured,
        temperature=0.2,
    )
    parsed = resp.choices[0].message.parsed
    if parsed is None:  # OpenAI signaled refusal
        raise APIError("OpenAI returned no parsed payload (refusal?)", request=None, body=None)

    usage = resp.usage
    tokens_in = getattr(usage, "prompt_tokens", 0) or 0
    tokens_out = getattr(usage, "completion_tokens", 0) or 0
    return StructureResult(
        data=parsed,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=_estimate_cost(tokens_in, tokens_out),
    )


async def structure_with_retry(transcript: str, *, max_attempts: int = 3) -> StructureResult | None:
    """Retry on API/validation errors with exponential backoff. Returns None on giving up."""
    if not get_settings().openai_api_key:
        log.info("structuring_skipped", reason="no_openai_api_key")
        return None

    last_err: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await structure_transcript(transcript)
        except (APIError, APIConnectionError, ValidationError, ValueError, httpx.HTTPError) as e:
            last_err = e
            log.warning(
                "structuring_failed",
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(e),
            )
            if attempt + 1 < max_attempts:
                await asyncio.sleep(2**attempt)
    log.error("structuring_giving_up", error=str(last_err) if last_err else "unknown")
    return None
