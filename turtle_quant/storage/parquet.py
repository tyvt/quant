"""Deterministic-enough Parquet I/O with atomic file replacement."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import os
from pathlib import Path
from typing import Mapping, Sequence
import unicodedata


def _portable_value(value: object) -> object:
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Parquet Decimal values must be finite")
        return str(value)
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Parquet datetime values must be timezone-aware")
        return (
            value.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        return {
            str(key): _portable_value(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_portable_value(item) for item in value]
    return value


def write_parquet_rows(
    path: str | Path,
    rows: Sequence[Mapping[str, object]],
    *,
    sort_keys: Sequence[str] = (),
) -> None:
    """Write rows atomically after canonical key sorting and value conversion."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional sync dependency
        raise RuntimeError("pyarrow is required for snapshot output") from exc
    materialized = [
        {str(key): _portable_value(value) for key, value in row.items()}
        for row in rows
    ]
    if sort_keys:
        materialized.sort(
            key=lambda row: tuple(
                (row.get(key) is None, str(row.get(key)))
                for key in sort_keys
            )
        )
    table = pa.Table.from_pylist(materialized)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        version="2.6",
        use_dictionary=False,
        write_statistics=True,
    )
    os.replace(temporary, target)
    # Arrow's allocator may retain the largest shard allocation for the
    # lifetime of a long-running full-market sync.  Release it between
    # independently published shards to keep memory bounded.
    del table
    del materialized
    try:
        pa.default_memory_pool().release_unused()
    except (OSError, RuntimeError):
        # The Windows mimalloc backend can sporadically report EINVAL after
        # successfully writing a shard.  Cleanup is best-effort and must not
        # turn a durable file into a failed ingestion step.
        pass


def read_parquet_rows(path: str | Path) -> list[dict[str, object]]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional sync dependency
        raise RuntimeError("pyarrow is required for snapshot input") from exc
    return pq.read_table(path).to_pylist()
