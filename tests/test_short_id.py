"""make_short_id basic shape."""

from __future__ import annotations

from app.store.short_id import make_short_id


def test_short_id_length_and_alphabet() -> None:
    sid = make_short_id()
    assert len(sid) == 6
    assert all((c.isalnum() and c.isupper()) or c.isdigit() for c in sid)


def test_short_id_random() -> None:
    seen = {make_short_id() for _ in range(50)}
    # Vanishingly unlikely to collide many times.
    assert len(seen) > 40
