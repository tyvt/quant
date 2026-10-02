"""Transient shard checkpoints used only inside snapshot staging."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Literal

from .snapshot import _canonical_json, sha256_file


CheckpointStatus = Literal["in_progress", "complete"]


def checkpoint_payload(
    *,
    domain: str,
    batch_id: str,
    prefix: str,
    status: CheckpointStatus,
    parquet_sha256: str | None,
    completed_symbols: tuple[str, ...] = (),
) -> dict[str, object]:
    if status not in {"in_progress", "complete"}:
        raise ValueError("checkpoint status must be in_progress or complete")
    if status == "complete" and not parquet_sha256:
        raise ValueError("a complete checkpoint requires parquet_sha256")
    return {
        "schema_version": 1,
        "domain": domain,
        "batch_id": batch_id,
        "prefix": prefix,
        "status": status,
        "parquet_sha256": parquet_sha256,
        "completed_symbols": list(completed_symbols),
        "last_updated_utc": (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        ),
    }


def write_checkpoint(path: str | Path, payload: dict[str, object]) -> None:
    checkpoint = Path(path)
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    temporary = checkpoint.with_name(
        f".{checkpoint.name}.{os.getpid()}.tmp"
    )
    temporary.write_text(_canonical_json(payload), encoding="utf-8")
    os.replace(temporary, checkpoint)


def should_skip_completed_shard(
    checkpoint_path: str | Path,
    parquet_path: str | Path,
) -> bool:
    checkpoint = Path(checkpoint_path)
    parquet = Path(parquet_path)
    if not checkpoint.is_file() or not parquet.is_file():
        return False
    try:
        payload = json.loads(checkpoint.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    expected = payload.get("parquet_sha256")
    return (
        payload.get("schema_version") == 1
        and payload.get("status") == "complete"
        and isinstance(expected, str)
        and bool(expected)
        and sha256_file(parquet) == expected
    )
