"""Allowlist behaviour."""

from __future__ import annotations

from app.auth import is_allowed
from app.config import get_settings


def test_allowed_users_are_parsed() -> None:
    ids = get_settings().allowed_user_ids
    assert 111 in ids
    assert 222 in ids


def test_is_allowed_accepts_listed_user() -> None:
    assert is_allowed(111) is True


def test_is_allowed_rejects_unknown_user() -> None:
    assert is_allowed(999) is False


def test_is_allowed_rejects_none() -> None:
    assert is_allowed(None) is False
