"""Allowlist authorization for Telegram users."""

from __future__ import annotations

from app.config import get_settings


def is_allowed(user_id: int | None) -> bool:
    """Return True iff the Telegram user ID is on the allowlist."""
    if user_id is None:
        return False
    return user_id in get_settings().allowed_user_ids
