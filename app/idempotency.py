"""In-memory idempotency cache for Telegram update_id deduplication."""

from __future__ import annotations

from collections import deque
from threading import Lock


class UpdateCache:
    """LRU-ish set of recently-seen Telegram update_ids."""

    def __init__(self, capacity: int = 1024) -> None:
        self._capacity = capacity
        self._set: set[int] = set()
        self._order: deque[int] = deque()
        self._lock = Lock()

    def seen(self, update_id: int) -> bool:
        """Return True if we've handled this update_id already, else record it."""
        with self._lock:
            if update_id in self._set:
                return True
            self._set.add(update_id)
            self._order.append(update_id)
            while len(self._order) > self._capacity:
                old = self._order.popleft()
                self._set.discard(old)
            return False


_cache = UpdateCache()


def already_handled(update_id: int) -> bool:
    return _cache.seen(update_id)


def reset_for_tests() -> None:
    global _cache
    _cache = UpdateCache()
