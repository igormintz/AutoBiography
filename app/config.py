"""Application settings loaded from environment variables."""

from __future__ import annotations

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _detect_serverless() -> bool:
    """True when running inside a serverless platform (Vercel, AWS Lambda, etc.)."""
    if os.environ.get("VERCEL"):
        return True
    if os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        return True
    flag = os.environ.get("SERVERLESS", "").strip().lower()
    return flag in {"1", "true", "yes"}


class Settings(BaseSettings):
    """All runtime configuration for the bot."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    telegram_bot_token: str = Field(default="")
    telegram_webhook_secret: str = Field(default="local-dev-secret")
    allowed_tg_user_ids: str = Field(default="")  # comma-separated

    # --- LLM ---
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="gpt-4o-mini")
    openai_whisper_model: str = Field(default="whisper-1")

    # --- Database ---
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:dev@localhost:5432/biography",
    )

    # --- Local output ---
    # On serverless platforms (Vercel) only `/tmp` is writable, so the default
    # is set there. Strongly prefer external storage (Postgres, S3, Drive) in
    # production — `/tmp` is per-invocation and not durable.
    output_dir: str = Field(default="./biography_output")

    # --- Whisper ---
    whisper_model: str = Field(default="ivrit-ai/whisper-large-v3-turbo-ct2")
    whisper_device: str = Field(default="cpu")  # "cuda" for GPU
    whisper_compute: str = Field(default="int8")  # "float16" for GPU
    hf_home: str = Field(default="./.hf-cache")

    # --- Misc ---
    log_level: str = Field(default="INFO")
    log_format: str = Field(default="json")  # "json" for prod, "console" for local dev
    timezone: str = Field(default="Asia/Jerusalem")
    base_url: str = Field(default="http://localhost:8080")

    # --- Serverless / cron ---
    cron_secret: str = Field(default="")

    @property
    def is_serverless(self) -> bool:
        """True when running on Vercel/Lambda/etc. — disables long-lived loops."""
        return _detect_serverless()

    @property
    def allowed_user_ids(self) -> set[int]:
        """Parse the comma-separated list once."""
        out: set[int] = set()
        for raw in self.allowed_tg_user_ids.split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                out.add(int(raw))
            except ValueError:
                continue
        return out


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor."""
    return Settings()
