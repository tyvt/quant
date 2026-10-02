"""Explicit gate for the not-ready buyback Parquet reader."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import NoReturn


_NOT_READY = (
    "buybacks Parquet reader is not ready under RULE_SPEC v1.2.0: "
    "exact execution dates and all-plan coverage are required"
)


class ParquetBuybackReader:
    def __init__(self, snapshot_root: str | Path) -> None:
        self.snapshot_root = Path(snapshot_root)

    @staticmethod
    def _not_ready() -> NoReturn:
        raise NotImplementedError(_NOT_READY)

    def buyback_events(
        self,
        security_id: str,
        start: date,
        end: date,
        *,
        as_of: date,
    ) -> NoReturn:
        self._not_ready()


__all__ = ["ParquetBuybackReader"]
