"""Per-chat conversational state for multi-step flows like /edit and /tags."""

from __future__ import annotations

from dataclasses import dataclass, field

# Simple in-process state. Single-user MVP — fine to lose on restart.
# Maps tg_chat_id → PendingAction.


@dataclass
class PendingAction:
    kind: str  # "edit" | "tags"
    short_id: str
    payload: dict = field(default_factory=dict)


_pending: dict[int, PendingAction] = {}


def set_pending(chat_id: int, action: PendingAction) -> None:
    _pending[chat_id] = action


def pop_pending(chat_id: int) -> PendingAction | None:
    return _pending.pop(chat_id, None)


def peek_pending(chat_id: int) -> PendingAction | None:
    return _pending.get(chat_id)


def clear_all_for_tests() -> None:
    _pending.clear()
