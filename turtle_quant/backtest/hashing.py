"""Canonical logical row hashing independent of Parquet physical bytes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
import unicodedata


def canonical_row_stream(
    rows: Iterable[Mapping[str, object]],
    *,
    schema_version: str,
    columns: tuple[str, ...],
    primary_key: tuple[str, ...],
) -> str:
    """Return a stable logical table representation for hashing."""

    if not isinstance(schema_version, str) or not schema_version:
        raise ValueError("schema_version must be non-empty")
    if not columns or len(set(columns)) != len(columns):
        raise ValueError("columns must be non-empty and unique")
    if not primary_key or len(set(primary_key)) != len(primary_key):
        raise ValueError("primary_key must be non-empty and unique")
    if not set(primary_key).issubset(columns):
        raise ValueError("primary_key must be a subset of columns")
    if any(not isinstance(item, str) or not item for item in columns + primary_key):
        raise ValueError("column names must be non-empty strings")

    normalized_rows: list[dict[str, object]] = []
    expected = set(columns)
    for row in rows:
        if not isinstance(row, Mapping) or set(row) != expected:
            raise ValueError("each row must exactly match the frozen columns")
        normalized_rows.append(
            {column: _canonical_value(row[column]) for column in columns}
        )
    normalized_rows.sort(
        key=lambda row: tuple(
            json.dumps(row[column], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for column in primary_key
        )
    )
    keys = [tuple(row[column] for column in primary_key) for row in normalized_rows]
    if len({json.dumps(key, ensure_ascii=False, sort_keys=True) for key in keys}) != len(keys):
        raise ValueError("logical rows must have unique primary keys")
    payload = {
        "schema_version": unicodedata.normalize("NFC", schema_version),
        "columns": list(columns),
        "primary_key": list(primary_key),
        "rows": [[row[column] for column in columns] for row in normalized_rows],
    }
    return unicodedata.normalize(
        "NFC",
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
    )


def logical_content_hash(
    rows: Iterable[Mapping[str, object]],
    *,
    schema_version: str,
    columns: tuple[str, ...],
    primary_key: tuple[str, ...],
) -> str:
    stream = canonical_row_stream(
        rows,
        schema_version=schema_version,
        columns=columns,
        primary_key=primary_key,
    )
    return hashlib.sha256(stream.encode("utf-8")).hexdigest()


def _canonical_value(value: object) -> object:
    if value is None or type(value) in (bool, int):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Decimal values must be finite")
        text = "0" if value == 0 else format(value.normalize(), "f")
        return {"type": "decimal", "value": text}
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("datetime values must be timezone-aware")
        return {"type": "datetime", "value": value.isoformat()}
    if type(value) is date:
        return {"type": "date", "value": value.isoformat()}
    if isinstance(value, Enum):
        return _canonical_value(value.value)
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    raise ValueError(f"unsupported canonical row value: {type(value).__name__}")


__all__ = ["canonical_row_stream", "logical_content_hash"]
