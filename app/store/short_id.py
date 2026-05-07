"""Generate short, human-friendly entry IDs."""

from __future__ import annotations

import secrets

# Crockford base32-ish: skip ambiguous characters (0/O, 1/I, etc.).
_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
_LENGTH = 6


def make_short_id() -> str:
    """Return a 6-character random ID like 'K7M2QX'."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
