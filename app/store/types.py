"""Cross-dialect SQLAlchemy types: ARRAY on Postgres, JSON on SQLite."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.types import TypeDecorator


class TextArray(TypeDecorator):
    """list[str] column.

    On Postgres → ``ARRAY(TEXT)`` (with GIN-indexable semantics).
    On SQLite → ``JSON`` (a list of strings stored as JSON text).
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Text()))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect):  # type: ignore[override]
        if value is None:
            return None
        # Coerce to plain list[str].
        return list(value)

    def process_result_value(self, value: Any, dialect):  # type: ignore[override]
        if value is None:
            return []
        return list(value)


class GUID(TypeDecorator):
    """UUID stored natively on Postgres and as 36-char text on SQLite."""

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[override]
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value: Any, dialect):  # type: ignore[override]
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value if dialect.name == "postgresql" else str(value)
        return value

    def process_result_value(self, value: Any, dialect):  # type: ignore[override]
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))
