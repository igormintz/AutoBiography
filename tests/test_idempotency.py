"""Telegram update_id deduplication."""

from __future__ import annotations

from app import idempotency


def setup_function() -> None:
    idempotency.reset_for_tests()


def test_first_seen_returns_false() -> None:
    assert idempotency.already_handled(1) is False


def test_repeat_returns_true() -> None:
    idempotency.already_handled(42)
    assert idempotency.already_handled(42) is True


def test_capacity_evicts_oldest() -> None:
    cache = idempotency.UpdateCache(capacity=3)
    for i in range(5):
        assert cache.seen(i) is False
    # After: 0 and 1 evicted; 2, 3, 4 still cached.
    assert cache.seen(2) is True
    assert cache.seen(3) is True
    assert cache.seen(4) is True
